# Shared persistent sliding-window throttling backed by PostgreSQL.
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, case, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.deps import current_user
from app.models import RateLimitBucket


# Used only when the database is temporarily unavailable; persisted hits remain authoritative.
_local_windows: dict[str, Deque[float]] = defaultdict(deque)
_local_lock = Lock()


def _subject_hash(name: str, subject: str) -> str:
    value = f"{name}\0{subject.strip().lower()}".encode()
    return hmac.new(settings.secret_key.encode(), value, hashlib.sha256).hexdigest()


def record_attempt(
    db: Session,
    name: str,
    subject: str,
    limit: int,
    seconds: int,
    cooldown_seconds: int = 900,
) -> tuple[int, datetime | None]:
    """Atomically record an attempt and return its count and active cooldown."""
    now = datetime.now(timezone.utc)
    key_hash = _subject_hash(name, subject)
    statement = pg_insert(RateLimitBucket).values(
        name=name,
        subject_hash=key_hash,
        window_started_at=now,
        hit_count=1,
        blocked_until=None,
        updated_at=now,
    )
    window_expired = RateLimitBucket.window_started_at <= now - timedelta(seconds=seconds)
    cooldown_active = and_(RateLimitBucket.blocked_until.is_not(None), RateLimitBucket.blocked_until > now)
    cooldown_expired = and_(RateLimitBucket.blocked_until.is_not(None), RateLimitBucket.blocked_until <= now)
    reset_window = or_(window_expired, cooldown_expired)
    next_count = case((reset_window, 1), else_=RateLimitBucket.hit_count + 1)
    statement = statement.on_conflict_do_update(
        index_elements=[RateLimitBucket.name, RateLimitBucket.subject_hash],
        set_={
            "window_started_at": case((reset_window, now), else_=RateLimitBucket.window_started_at),
            "hit_count": next_count,
            "blocked_until": case(
                (cooldown_active, RateLimitBucket.blocked_until),
                (reset_window, None),
                (RateLimitBucket.hit_count >= limit, now + timedelta(seconds=cooldown_seconds)),
                else_=None,
            ),
            "updated_at": now,
        },
    ).returning(RateLimitBucket.hit_count, RateLimitBucket.blocked_until)
    hit_count, blocked_until = db.execute(statement).one()
    if secrets.randbelow(100) == 0:
        db.execute(
            delete(RateLimitBucket).where(
                RateLimitBucket.updated_at < now - timedelta(days=7)
            )
        )
    db.commit()
    if blocked_until is not None and blocked_until <= now:
        blocked_until = None
    return hit_count, blocked_until


def get_attempt_count(db: Session, name: str, subject: str, seconds: int) -> int:
    now = datetime.now(timezone.utc)
    row = db.execute(
        select(RateLimitBucket.window_started_at, RateLimitBucket.hit_count, RateLimitBucket.blocked_until).where(
            RateLimitBucket.name == name,
            RateLimitBucket.subject_hash == _subject_hash(name, subject),
        )
    ).first()
    if row is None:
        return 0
    window_started_at, hit_count, blocked_until = row
    if window_started_at <= now - timedelta(seconds=seconds):
        return 0
    if blocked_until is not None and blocked_until <= now:
        return 0
    return hit_count


def clear_attempts(db: Session, name: str, subject: str) -> None:
    db.query(RateLimitBucket).filter(
        RateLimitBucket.name == name,
        RateLimitBucket.subject_hash == _subject_hash(name, subject),
    ).delete(synchronize_session=False)
    db.commit()


def _record_local_fallback(name: str, subject: str, limit: int, seconds: int) -> None:
    key = f"{name}:{_subject_hash(name, subject)}"
    now = time.monotonic()
    cutoff = now - seconds
    with _local_lock:
        window = _local_windows[key]
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")
        window.append(now)


def rate_limit(
    name: str,
    limit: int,
    seconds: int,
    *,
    key_field: str | None = None,
    cooldown_seconds: int = 900,
) -> Callable:
    """Return a shared sliding-window dependency keyed by account, IP, or form field."""
    async def _dependency(request: Request, user=Depends(current_user)) -> None:
        client_ip = request.client.host if request.client else "unknown"
        if key_field is not None:
            form = await request.form()
            subject = str(form.get(key_field, "")).strip().lower() or client_ip
        elif user is not None:
            subject = f"user:{user.id}"
        else:
            subject = f"ip:{client_ip}"

        db = SessionLocal()
        try:
            _, blocked_until = record_attempt(db, name, subject, limit, seconds, cooldown_seconds)
        except Exception:
            db.rollback()
            _record_local_fallback(name, subject, limit, seconds)
            return
        finally:
            db.close()

        if blocked_until is not None:
            retry_after = max(1, math.ceil((blocked_until - datetime.now(timezone.utc)).total_seconds()))
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
