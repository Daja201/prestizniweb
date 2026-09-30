# Tests for authentication routes and security behaviour.
from __future__ import annotations

import hmac
import hashlib
from io import BytesIO
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app.core.config import settings
from app.core.storage import abs_path
from app.models import LoginToken, User, UserSession
from app.services.sessions import SESSION_COOKIE, create_session


def _hmac(value: str) -> str:
    return hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


# ── email validation ─────────────────────────────────────────────────────────

def test_login_any_email_domain_creates_token(client, db):
    resp = client.post("/login", data={"email": "user@example.net"}, follow_redirects=False)
    assert resp.status_code == 200
    assert "check_email" in resp.text or "Zkontroluj" in resp.text
    assert db.query(LoginToken).count() == 1


def test_login_plus_alias_allowed(client, db):
    resp = client.post("/login", data={"email": "a+b@example.net"}, follow_redirects=False)
    assert resp.status_code == 200
    assert db.query(LoginToken).count() == 1


def test_login_uppercase_normalised(client, db):
    email = "Jan.Novak@Example.NET".upper()
    resp = client.post("/login", data={"email": email}, follow_redirects=False)
    assert resp.status_code == 200
    token = db.query(LoginToken).first()
    assert token is not None
    assert token.email == email.lower()


def test_login_valid_email_creates_token(client, db):
    resp = client.post("/login", data={"email": "jan@example.org"}, follow_redirects=False)
    assert resp.status_code == 200
    assert db.query(LoginToken).count() == 1


# ── token single use ──────────────────────────────────────────────────────────

def test_token_single_use(client, db):
    import secrets
    raw = secrets.token_urlsafe(32)
    code = "123456"
    now = datetime.now(timezone.utc)
    lt = LoginToken(
        email="jan@example.net",
        token_hash=_hmac(raw),
        code_hash=_hmac(code),
        attempts=0,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(lt)
    db.commit()

    resp1 = client.post("/auth/verify", data={"token": raw}, follow_redirects=False)
    assert resp1.status_code == 303

    resp2 = client.post("/auth/verify", data={"token": raw}, follow_redirects=False)
    assert resp2.status_code == 200  # renders login with error (token used)


# ── code attempts limit ───────────────────────────────────────────────────────

def test_code_attempts_limit(client, db):
    import secrets
    raw = secrets.token_urlsafe(32)
    email = "test@example.net"
    now = datetime.now(timezone.utc)
    lt = LoginToken(
        email=email,
        token_hash=_hmac(raw),
        code_hash=_hmac("999999"),
        attempts=0,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(lt)
    db.commit()

    for _ in range(5):
        client.post("/auth/code", data={"email": email, "code": "000000"})

    # 6th attempt should burn the token
    resp = client.post("/auth/code", data={"email": email, "code": "000000"})
    db.refresh(lt)
    assert lt.used_at is not None


# ── banned user refused ───────────────────────────────────────────────────────

def test_banned_user_cannot_login(client, db, make_user):
    import secrets
    user = make_user(email="banned@example.net", status="banned")
    raw = secrets.token_urlsafe(32)
    code = "654321"
    now = datetime.now(timezone.utc)
    lt = LoginToken(
        email=user.email,
        token_hash=_hmac(raw),
        code_hash=_hmac(code),
        attempts=0,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(lt)
    db.commit()

    resp = client.post("/auth/verify", data={"token": raw}, follow_redirects=False)
    assert resp.status_code == 200
    assert "zablokován" in resp.text or "Přihlášení není možné" in resp.text


# ── open redirect protection ──────────────────────────────────────────────────

@pytest.mark.parametrize("bad_next", [
    "//evil.com",
    "https://evil.com",
    "http://evil.com/steal",
    "//evil.com/path",
])
def test_open_redirect_blocked(client, db, make_user, bad_next):
    user = make_user(email="redirect@example.net")
    import secrets
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    lt = LoginToken(
        email=user.email,
        token_hash=_hmac(raw),
        code_hash=_hmac("000000"),
        attempts=0,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(lt)
    db.commit()
    resp = client.post("/auth/verify", data={"token": raw, "next": bad_next}, follow_redirects=False)
    if resp.status_code == 303:
        assert resp.headers["location"] in ("/", "http://testserver/")


# ── auth-check endpoint ───────────────────────────────────────────────────────

def test_auth_check_no_session_returns_401(client):
    resp = client.get("/internal/auth-check")
    assert resp.status_code == 401


def test_auth_check_valid_session_returns_204(client, db, make_user, login):
    user = make_user()
    login(client, user)
    resp = client.get("/internal/auth-check")
    assert resp.status_code == 204


# ── origin / csrf check ───────────────────────────────────────────────────────

def test_cross_site_post_rejected(client, db, make_user, login):
    user = make_user()
    login(client, user)
    resp = client.post(
        "/me",
        data={"display_name": "Hacker"},
        headers={"Origin": "https://evil.com"},
    )
    assert resp.status_code == 403


def test_profile_update_persists_name_and_avatar(client, db, make_user, login, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    user = make_user()
    login(client, user)

    image_data = BytesIO()
    Image.new("RGB", (80, 60), "teal").save(image_data, "PNG")
    response = client.post(
        "/me",
        data={"display_name": "Updated Student", "avatar": "circle", "avatar_character": "@"},
        files={"avatar_file": ("avatar.png", image_data.getvalue(), "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db.expire_all()
    updated = db.get(User, user.id)
    assert updated.display_name == "Updated Student"
    assert updated.avatar == "circle"
    assert updated.avatar_character == "@"
    assert updated.avatar_path
    assert abs_path(updated.avatar_path).is_file()


def test_blank_avatar_character_keeps_round_initial(client, db, make_user, login):
    user = make_user()
    login(client, user)

    response = client.post("/me", data={"display_name": user.display_name, "avatar": "circle", "avatar_character": ""})

    assert response.status_code == 303
    db.expire_all()
    updated = db.get(User, user.id)
    assert updated.avatar == "circle"
    assert updated.avatar_character is None


def test_avatar_character_must_be_printable_ascii(client, make_user, login):
    user = make_user()
    login(client, user)

    response = client.post("/me", data={"display_name": user.display_name, "avatar": "circle", "avatar_character": "é"})

    assert response.status_code == 200
    assert "ASCII" in response.text


def test_square_avatar_is_admin_only(client, db, make_user, login):
    user = make_user()
    login(client, user)
    response = client.post("/me", data={"display_name": user.display_name, "avatar": "square", "avatar_character": "X"})
    assert response.status_code == 200
    assert "pouze administrátorům" in response.text
    db.refresh(user)
    assert user.avatar == "circle"

    admin = make_user(role="admin")
    client.cookies.clear()
    login(client, admin)
    response = client.post("/me", data={"display_name": admin.display_name, "avatar": "square", "avatar_character": "X"})
    assert response.status_code == 303
    db.refresh(admin)
    assert admin.avatar == "square"
    assert admin.avatar_character == "X"


# ── account deletion anonymises data ─────────────────────────────────────────

def test_account_deletion_anonymises(client, db, make_user, login):
    user = make_user(email="del@example.net")
    uid = user.id
    login(client, user)

    resp = client.post("/me/delete", data={"confirm": "SMAZAT"}, follow_redirects=False)
    assert resp.status_code == 303

    db.expire_all()
    updated = db.get(User, uid)
    assert updated.status == "deleted"
    assert "@deleted.invalid" in updated.email
    assert updated.display_name == "Smazaný uživatel"
    assert db.query(UserSession).filter(UserSession.user_id == uid).count() == 0