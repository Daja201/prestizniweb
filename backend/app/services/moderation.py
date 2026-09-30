# Shared moderation status operations and target validation.
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Meme, Quote, Resource, SchoolClass, User
from app.services.audit import log

TARGETS: dict[str, tuple[type[Any], set[str]]] = {
    "meme": (Meme, {"visible", "hidden", "deleted"}),
    "quote": (Quote, {"pending", "visible", "hidden", "deleted"}),
    "resource": (Resource, {"visible", "hidden", "deleted"}),
    "class": (SchoolClass, {"active", "hidden"}),
    "user": (User, {"active", "banned", "deleted"}),
}


def get_target(db: Session, target_type: str, target_id: int) -> Any | None:
    """Return a target object or None when the type is unsupported/missing."""
    spec = TARGETS.get(target_type)
    if spec is None:
        return None
    return db.scalar(select(spec[0]).where(spec[0].id == target_id))


def target_is_deleted(target_type: str, target: Any) -> bool:
    return target is None or getattr(target, "status", None) == "deleted"


def set_status(
    db: Session,
    target_type: str,
    target_id: int,
    status: str,
    actor_id: int | None,
    reason: str = "",
) -> None:
    """Validate and change a moderation target status in the current transaction."""
    spec = TARGETS.get(target_type)
    if spec is None:
        raise ValueError("Neplatný typ cíle.")
    if status not in spec[1]:
        raise ValueError("Neplatný stav cíle.")
    target = get_target(db, target_type, target_id)
    if target is None:
        raise LookupError("Cíl nebyl nalezen.")
    target.status = status
    log(db, actor_id, "set_status", target_type, target_id, {"status": status, "reason": reason})
