# Audit logging service for moderator and administrative actions.
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def log(
    db: Session,
    actor_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    meta: dict | None = None,
) -> None:
    """Append one audit record to the current transaction."""
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=meta or {},
        )
    )
