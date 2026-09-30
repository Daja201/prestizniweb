# FastAPI dependencies for authentication / authorization.
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, Response

from app.models import User


def current_user(request: Request) -> User | None:
    """Return the logged-in user or None (set by auth middleware)."""
    return getattr(request.state, "user", None)


def require_user(request: Request, user: User | None = Depends(current_user)) -> User:
    """Require any authenticated user; redirect to /login otherwise."""
    if user is None:
        _redirect_to_login(request)
    return user  # type: ignore[return-value]


def require_mod(request: Request, user: User | None = Depends(current_user)) -> User:
    """Require moderator or admin role."""
    if user is None:
        _redirect_to_login(request)
    if user.role not in ("moderator", "admin"):  # type: ignore[union-attr]
        raise _forbidden(request)
    return user  # type: ignore[return-value]


def require_admin(request: Request, user: User | None = Depends(current_user)) -> User:
    """Require admin role."""
    if user is None:
        _redirect_to_login(request)
    if user.role != "admin":  # type: ignore[union-attr]
        raise _forbidden(request)
    return user  # type: ignore[return-value]


# ── helpers ──────────────────────────────────────────────────────────────────

def _redirect_to_login(request: Request) -> None:
    """Raise a redirect to /login for browser requests or HX-Redirect for HTMX."""
    next_path = request.url.path
    if request.headers.get("HX-Request"):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            headers={"HX-Redirect": f"/login?next={next_path}"},
        )
    from fastapi import HTTPException
    raise HTTPException(
        status_code=303,
        headers={"Location": f"/login?next={next_path}"},
    )


def _forbidden(request: Request):
    from fastapi import HTTPException
    if request.headers.get("HX-Request"):
        return HTTPException(status_code=403, detail="Přístup odmítnut.")
    return HTTPException(status_code=403)