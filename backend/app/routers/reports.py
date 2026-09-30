# Report submission endpoints and target validation.
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import rate_limit
from app.core.templates import render
from app.models import ClassMember, Meme, Quote, Report, Resource, SchoolClass, User
from app.services import audit, moderation

router = APIRouter()

TARGET_MODELS = {
    "meme": Meme,
    "quote": Quote,
    "resource": Resource,
    "user": User,
    "class": SchoolClass,
}
REASONS = {"spam", "harassment", "personal_info", "inappropriate", "copyright", "other"}


def _target(db: Session, target_type: str, target_id: int):
    model = TARGET_MODELS.get(target_type)
    if model is None:
        return None
    return db.scalar(select(model).where(model.id == target_id))


def _author_id(target_type: str, target):
    if target_type == "user":
        return target.id
    return getattr(target, "author_id", None) or getattr(target, "created_by", None)


@router.post("/reports", response_class=HTMLResponse, dependencies=[Depends(rate_limit("reports", 20, 3600))])
def create_report(
    request: Request,
    target_type: str = Form(...),
    target_id: int = Form(...),
    reason: str = Form(...),
    details: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Create a report and auto-hide content at the configured threshold."""
    if target_type not in TARGET_MODELS or reason not in REASONS:
        return HTMLResponse("Invalid data.", status_code=400)
    details = details.strip()
    if len(details) > 500:
        return HTMLResponse("Details may be at most 500 characters.", status_code=400)
    target = _target(db, target_type, target_id)
    if target is None or getattr(target, "status", None) == "deleted":
        return HTMLResponse("Obsah nebyl nalezen.", status_code=404)
    if _author_id(target_type, target) == user.id:
        return HTMLResponse("You cannot report your own content.", status_code=400)

    existing = db.scalar(
        select(Report).where(
            Report.reporter_id == user.id,
            Report.target_type == target_type,
            Report.target_id == target_id,
        )
    )
    if existing:
        return HTMLResponse("You have already reported this.", status_code=409)

    report = Report(
        reporter_id=user.id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        details=details,
    )
    db.add(report)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return HTMLResponse("You have already reported this.", status_code=409)

    open_count = db.scalar(
        select(func.count(func.distinct(Report.reporter_id))).where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.status == "open",
        )
    ) or 0
    if open_count >= settings.auto_hide_report_threshold:
        if target_type in {"meme", "quote", "resource", "class"} and getattr(target, "status", None) != "hidden":
            moderation.set_status(db, target_type, target_id, "hidden", user.id, "report threshold")
            audit.log(db, user.id, "auto_hide", target_type, target_id, {"open_reports": open_count})

    db.commit()
    return HTMLResponse("<div class=\"flash flash-success\">Thank you, moderators will look into it.</div>")
