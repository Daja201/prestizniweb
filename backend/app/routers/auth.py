# Authentication router: login, verify, logout, profile, session middleware.
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from email_validator import validate_email, EmailNotValidError
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, SessionLocal
from app.core.deps import current_user, require_user
from app.core.flash import flash
from app.core.ratelimit import rate_limit
from app.core.templates import render
from app.models import LoginToken, User
from app.services.mailer import send_login_email
from app.services.sessions import (
    SESSION_COOKIE,
    create_session,
    destroy_all_sessions,
    destroy_session,
    get_user_by_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_TOKEN_TTL = timedelta(minutes=15)
_MAX_CODE_ATTEMPTS = 5
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days in seconds

_EMAIL_RE = re.compile(
    r"^[a-z0-9._-]+@(?P<domain>[a-z0-9.-]+)$"
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _hmac(value: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def _set_session_cookie(response: Response, raw_token: str) -> None:
    secure = settings.base_url.startswith("https")
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=_COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _safe_next(next_param: str | None) -> str:
    """Allow only local paths (single leading slash, no scheme or double slash)."""
    if next_param and re.match(r"^/[^/]", next_param):
        return next_param
    return "/"


def _read_upload_sync(upload) -> bytes:
    """Read an UploadFile's bytes from sync code (mirrors the form-parsing pattern above)."""
    import asyncio

    async def _get_bytes():
        return await upload.read()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_get_bytes())
    finally:
        loop.close()


def _display_name_from_email(local: str) -> str:
    """'jan.novak' -> 'Jan Novak'"""
    return " ".join(part.capitalize() for part in local.replace(".", " ").replace("_", " ").split())


def _validate_school_email(email: str) -> str:
    """Return normalised email or raise ValueError with a Czech message."""
    email = email.strip().lower()
    # Disallow + aliases
    if "+" in email:
        raise ValueError("Aliasy s '+' nejsou povoleny.")
    try:
        info = validate_email(email, check_deliverability=False)
        email = info.normalized.lower()
    except EmailNotValidError:
        raise ValueError("Neplatná e-mailová adresa.")

    match = _EMAIL_RE.match(email)
    if not match or match.group("domain") != settings.allowed_email_domain:
        raise ValueError(
            f"Přihlášení je možné pouze pro adresy @{settings.allowed_email_domain}."
        )
    return email


def _get_or_create_user(db: Session, email: str) -> User:
    user: User | None = db.query(User).filter(User.email == email).first()
    if user is None:
        local = email.split("@")[0]
        display_name = _display_name_from_email(local)
        role = "admin" if email in settings.admin_email_list else "student"
        user = User(
            email=email,
            display_name=display_name,
            role=role,
            status="active",
        )
        db.add(user)
        db.flush()
    return user


# ── middleware / setup ────────────────────────────────────────────────────────

class _AuthMiddleware:
    """Load session cookie -> request.state.user; enforce Origin check."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import Response as StarletteResponse

        request = StarletteRequest(scope, receive)
        request.state.user = None

        # Load session
        raw = request.cookies.get(SESSION_COOKIE)
        if raw:
            db = SessionLocal()
            try:
                request.state.user = get_user_by_token(db, raw)
            finally:
                db.close()

        # CSRF: reject cross-origin unsafe methods (Origin/Referer check)
        method = request.method.upper()
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            # Skip CSRF for auth endpoints (they validate tokens instead)
            path = request.url.path
            if not path.startswith("/auth/") and path not in ("/login", "/takedown"):
                origin = request.headers.get("Origin") or request.headers.get("Referer", "")
                if origin:
                    parsed = urlparse(origin)
                    allowed = urlparse(settings.base_url)
                    if parsed.netloc != allowed.netloc:
                        response = StarletteResponse(
                            "Zakázaný přístup (CSRF).", status_code=403
                        )
                        await response(scope, receive, send)
                        return

        await self.app(scope, receive, send)


def setup(app: FastAPI) -> None:
    """Register auth middleware and exception handlers."""
    from starlette.middleware import Middleware
    app.add_middleware(_AuthMiddleware)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 303:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        if exc.status_code == 401 and exc.headers and "HX-Redirect" in exc.headers:
            return Response(status_code=401, headers={"HX-Redirect": exc.headers["HX-Redirect"]})
        if exc.status_code == 403:
            if request.headers.get("HX-Request") == "true" or "text/html" not in request.headers.get("accept", "text/html"):
                return PlainTextResponse("Přístup odepřen.", status_code=403)
            return render(request, "errors/403.html", status_code=403)
        if exc.status_code == 404:
            if request.headers.get("HX-Request") == "true" or "text/html" not in request.headers.get("accept", "text/html"):
                return PlainTextResponse("Nenalezeno", status_code=404)
            return render(request, "errors/404.html", status_code=404)
        if exc.status_code == 429:
            if request.headers.get("HX-Request") == "true" or "text/html" not in request.headers.get("accept", "text/html"):
                return PlainTextResponse(exc.detail or "Příliš mnoho požadavků.", status_code=429)
            return render(
                request, "errors/500.html", status_code=429,
                error_message=exc.detail or "Příliš mnoho požadavků."
            )
        raise exc


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if request.state.user:
        return RedirectResponse("/", status_code=303)
    return render(request, "auth/login.html", next=next)


_rate_limit_email = rate_limit("login_email", limit=5, seconds=3600)
_rate_limit_ip = rate_limit("login_ip", limit=20, seconds=3600)


@router.post("/login")
def login_post(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    async def _inner():
        # Apply rate limits inline (they're sync dependencies but we call manually)
        pass

    # Parse form
    import asyncio
    form_data = asyncio.get_event_loop().run_until_complete(request.form()) if False else None

    # Use sync form parsing via starlette
    from starlette.datastructures import FormData
    import anyio

    async def _get_form():
        return await request.form()

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        form = loop.run_until_complete(_get_form())
    finally:
        loop.close()

    email_raw = form.get("email", "")
    next_path = form.get("next", "/")

    try:
        email = _validate_school_email(str(email_raw))
    except ValueError:
        # Always show "check your email" to avoid enumeration
        pass
    else:
        # Create token
        raw_token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        token_hash = _hmac(raw_token)
        code_hash = _hmac(code)
        now = datetime.now(timezone.utc)

        lt = LoginToken(
            email=email,
            token_hash=token_hash,
            code_hash=code_hash,
            attempts=0,
            expires_at=now + _TOKEN_TTL,
            ip=request.client.host if request.client else None,
        )
        db.add(lt)
        db.commit()

        link = f"{settings.base_url}/auth/verify?token={raw_token}"
        background_tasks.add_task(send_login_email, email, link, code)

    return render(request, "auth/check_email.html", next=_safe_next(next_path))


@router.get("/auth/verify", response_class=HTMLResponse)
def verify_get(request: Request, token: str = ""):
    """Show the confirm page; does NOT consume the token (safe-link prefetch protection)."""
    return render(request, "auth/confirm.html", token=token)


@router.post("/auth/verify")
def verify_post(
    request: Request,
    db: Session = Depends(get_db),
):
    import asyncio

    async def _get_form():
        return await request.form()

    loop = asyncio.new_event_loop()
    try:
        form = loop.run_until_complete(_get_form())
    finally:
        loop.close()

    raw_token = str(form.get("token", ""))
    next_path = _safe_next(str(form.get("next", "/")))
    return _consume_token(request, db, raw_token, next_path)


@router.post("/auth/code")
def code_post(request: Request, db: Session = Depends(get_db)):
    import asyncio

    async def _get_form():
        return await request.form()

    loop = asyncio.new_event_loop()
    try:
        form = loop.run_until_complete(_get_form())
    finally:
        loop.close()

    email = str(form.get("email", "")).strip().lower()
    code = str(form.get("code", "")).strip()
    next_path = _safe_next(str(form.get("next", "/")))
    now = datetime.now(timezone.utc)

    lt: LoginToken | None = (
        db.query(LoginToken)
        .filter(
            LoginToken.email == email,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
        .order_by(LoginToken.created_at.desc())
        .first()
    )
    if lt is None:
        resp = render(request, "auth/check_email.html", next=next_path, error="Neplatný nebo expirovaný kód.")
        return resp

    lt.attempts += 1
    if lt.attempts > _MAX_CODE_ATTEMPTS:
        lt.used_at = now
        db.commit()
        return render(request, "auth/login.html", error="Příliš mnoho pokusů. Vyžádej nový odkaz.", next=next_path)

    if not hmac.compare_digest(_hmac(code), lt.code_hash):
        db.commit()
        return render(request, "auth/check_email.html", next=next_path, error=f"Špatný kód. Zbývá pokusů: {_MAX_CODE_ATTEMPTS - lt.attempts}.")

    lt.used_at = now
    db.commit()
    return _finish_login(request, db, lt.email, next_path)


def _consume_token(request: Request, db: Session, raw_token: str, next_path: str):
    token_hash = _hmac(raw_token)
    now = datetime.now(timezone.utc)

    lt: LoginToken | None = (
        db.query(LoginToken)
        .filter(
            LoginToken.token_hash == token_hash,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
        .first()
    )
    if lt is None:
        resp = render(request, "auth/login.html", error="Odkaz je neplatný nebo expiroval. Vyžádej nový.")
        return resp

    lt.used_at = now
    db.commit()
    return _finish_login(request, db, lt.email, next_path)


def _finish_login(request: Request, db: Session, email: str, next_path: str):
    user = _get_or_create_user(db, email)
    if user.status in ("banned", "deleted"):
        db.commit()
        return render(request, "auth/login.html", error="Přihlášení není možné. Účet byl zablokován nebo smazán.")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    raw_token = create_session(db, user, request.client.host if request.client else None, request.headers.get("user-agent"))
    response = RedirectResponse(next_path, status_code=303)
    _set_session_cookie(response, raw_token)
    return response


@router.post("/logout")
def logout(request: Request, response: Response):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        from app.core.db import SessionLocal
        db = SessionLocal()
        try:
            destroy_session(db, raw)
        finally:
            db.close()
    redir = RedirectResponse("/", status_code=303)
    _clear_session_cookie(redir)
    return redir


@router.get("/internal/auth-check")
def auth_check(request: Request):
    """Caddy forward_auth endpoint: 204 active session, 401 otherwise."""
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        db = SessionLocal()
        try:
            user = get_user_by_token(db, raw)
        finally:
            db.close()
        if user:
            return Response(status_code=204)
    return Response(status_code=401)


@router.get("/me", response_class=HTMLResponse)
def me_get(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    from app.models import ClassMember, SchoolClass
    memberships = (
        db.query(ClassMember, SchoolClass)
        .join(SchoolClass, ClassMember.class_id == SchoolClass.id)
        .filter(ClassMember.user_id == user.id)
        .all()
    )
    return render(request, "auth/me.html", memberships=memberships)


@router.post("/me")
def me_post(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    import asyncio

    async def _get_form():
        return await request.form()

    loop = asyncio.new_event_loop()
    try:
        form = loop.run_until_complete(_get_form())
    finally:
        loop.close()

    display_name = str(form.get("display_name", "")).strip()
    avatar = str(form.get("avatar", "circle")).strip().lower()
    remove_photo = str(form.get("remove_avatar_photo", "")).strip() == "1"
    upload = form.get("avatar_file")

    # Validate: 2-60 chars, no control characters
    if not (2 <= len(display_name) <= 60):
        return render(request, "auth/me.html", error="Jméno musí mít 2–60 znaků.")
    if any(unicodedata.category(c).startswith("C") for c in display_name):
        return render(request, "auth/me.html", error="Jméno obsahuje nepovoluné znaky.")

    if avatar not in {"circle", "square", "triangle", "dot"}:
        return render(request, "auth/me.html", error="Neplatný profilový symbol.")

    from app.core.storage import save_bytes, delete as storage_delete
    from app.services.images import process_avatar_image

    new_avatar_path = None
    if upload is not None and getattr(upload, "filename", ""):
        raw = _read_upload_sync(upload)
        if raw:
            try:
                processed = process_avatar_image(raw)
            except ValueError as exc:
                return render(request, "auth/me.html", error=str(exc))
            new_avatar_path = save_bytes("avatars", processed, "webp")

    user.display_name = display_name
    user.avatar = avatar
    if new_avatar_path:
        old_path = user.avatar_path
        user.avatar_path = new_avatar_path
        storage_delete(old_path)
    elif remove_photo and user.avatar_path:
        storage_delete(user.avatar_path)
        user.avatar_path = None
    db.commit()
    response = RedirectResponse("/me", status_code=303)
    flash(response, "Settings saved.", "success")
    return response


@router.post("/me/delete")
def me_delete(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    import asyncio

    async def _get_form():
        return await request.form()

    loop = asyncio.new_event_loop()
    try:
        form = loop.run_until_complete(_get_form())
    finally:
        loop.close()

    confirm = str(form.get("confirm", "")).strip()
    if confirm != "SMAZAT":
        return render(request, "auth/me.html", error="Pro smazání účtu napiš SMAZAT.")

    from app.models import Meme, Quote, Resource, ClassMember, MemeLike, QuoteVote, ResourceVote, SchoolClass
    from app.core.storage import delete as storage_delete

    now = datetime.now(timezone.utc)

    # Remove the uploaded profile photo, if any.
    if user.avatar_path:
        storage_delete(user.avatar_path)
        user.avatar_path = None

    # Hand off ownership of any class profiles this user created, so they
    # don't become permanently unmanageable once this account is anonymised.
    owned_classes = db.query(SchoolClass).filter(SchoolClass.created_by == user.id).all()
    for school_class in owned_classes:
        successor = (
            db.query(ClassMember)
            .filter(
                ClassMember.class_id == school_class.id,
                ClassMember.user_id != user.id,
                ClassMember.status == "approved",
            )
            .order_by(ClassMember.created_at.asc())
            .first()
        )
        if successor:
            successor.role = "owner"
            school_class.created_by = successor.user_id
        else:
            # No one left to hand it to; hide it rather than leave an
            # ownerless, uneditable-by-anyone-but-a-moderator profile.
            school_class.status = "hidden"

    # Anonymise memes
    memes = db.query(Meme).filter(Meme.author_id == user.id, Meme.status != "deleted").all()
    for m in memes:
        storage_delete(m.image_path)
        storage_delete(m.thumb_path)
        m.status = "deleted"

    # Anonymise resources
    resources = db.query(Resource).filter(Resource.author_id == user.id, Resource.status != "deleted").all()
    for r in resources:
        if r.file_path:
            storage_delete(r.file_path)
        r.status = "deleted"

    # Anonymise quotes
    db.query(Quote).filter(Quote.author_id == user.id).update({"status": "deleted"})

    # Remove votes/likes (adjust counters atomically)
    from sqlalchemy import text
    for ml in db.query(MemeLike).filter(MemeLike.user_id == user.id).all():
        db.execute(text("UPDATE memes SET likes_count = likes_count - 1 WHERE id = :id"), {"id": ml.meme_id})
        db.delete(ml)
    for qv in db.query(QuoteVote).filter(QuoteVote.user_id == user.id).all():
        db.execute(text("UPDATE quotes SET votes_count = votes_count - 1 WHERE id = :id"), {"id": qv.quote_id})
        db.delete(qv)
    for rv in db.query(ResourceVote).filter(ResourceVote.user_id == user.id).all():
        db.execute(text("UPDATE resources SET upvotes_count = upvotes_count - 1 WHERE id = :id"), {"id": rv.resource_id})
        db.delete(rv)

    # Remove class memberships
    db.query(ClassMember).filter(ClassMember.user_id == user.id).delete()

    # Destroy all sessions
    raw = request.cookies.get(SESSION_COOKIE)
    destroy_all_sessions(db, user.id)

    # Anonymise user record
    user.status = "deleted"
    user.deleted_at = now
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.display_name = "Smazaný uživatel"

    db.commit()

    response = RedirectResponse("/", status_code=303)
    _clear_session_cookie(response)
    return response