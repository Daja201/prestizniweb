# Session management: create, look up, destroy user sessions.
from __future__ import annotations

import hmac
import hashlib
import logging
import random
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User, UserSession, LoginToken

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session"
_SESSION_LIFETIME = timedelta(days=30)
_RENEWAL_INTERVAL = timedelta(hours=1)


def _hmac(value: str) -> str:
    """Return HMAC-SHA256 hex digest keyed by SECRET_KEY."""
    return hmac.new(
        settings.secret_key.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def create_session(
    db: Session,
    user: User,
    ip: str | None,
    user_agent: str | None,
) -> str:
    """Create a new session; return the raw token (stored only as its hash)."""
    raw = secrets.token_urlsafe(32)
    token_hash = _hmac(raw)
    now = datetime.now(timezone.utc)
    expires = now + _SESSION_LIFETIME

    session = UserSession(
        token_hash=token_hash,
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=expires,
        ip=ip,
        user_agent=(user_agent or "")[:255],
    )
    db.add(session)
    db.commit()

    if random.randint(1, 50) == 1:  # ~2 % of logins
        _purge_expired(db)

    return raw


def get_user_by_token(db: Session, raw: str) -> User | None:
    """Return the active user for a session token, renew if needed."""
    token_hash = _hmac(raw)
    now = datetime.now(timezone.utc)

    row: UserSession | None = (
        db.query(UserSession)
        .filter(
            UserSession.token_hash == token_hash,
            UserSession.expires_at > now,
        )
        .first()
    )
    if row is None:
        return None

    user: User | None = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None

    # Sliding renewal at most once per hour
    if now - row.last_seen_at > _RENEWAL_INTERVAL:
        row.last_seen_at = now
        row.expires_at = now + _SESSION_LIFETIME
        db.commit()

    return user


def destroy_session(db: Session, raw: str) -> None:
    """Delete a single session by its raw token."""
    token_hash = _hmac(raw)
    db.query(UserSession).filter(UserSession.token_hash == token_hash).delete()
    db.commit()


def destroy_all_sessions(db: Session, user_id: int) -> None:
    """Delete all sessions for a user (used on account deletion)."""
    db.query(UserSession).filter(UserSession.user_id == user_id).delete()
    db.commit()


def _purge_expired(db: Session) -> None:
    """Remove expired sessions and login tokens (best-effort)."""
    now = datetime.now(timezone.utc)
    try:
        db.query(UserSession).filter(UserSession.expires_at <= now).delete()
        db.query(LoginToken).filter(LoginToken.expires_at <= now).delete()
        db.commit()
    except Exception:
        logger.exception("Error purging expired rows")
        db.rollback()