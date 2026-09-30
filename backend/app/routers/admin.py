# Moderator and administrator dashboards and moderation actions.
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.db import get_db
from app.core.deps import require_admin, require_mod
from app.core.flash import flash
from app.core.templates import render
from app.models import AuditLog, ClassMember, Meme, Quote, Report, Resource, SchoolClass, TakedownRequest, User, UserSession
from app.services import audit, moderation

router = APIRouter(prefix="/admin")


def _page(value: int | None) -> int:
    return max(1, value or 1)


def _reports_for_target(db: Session, target_type: str, target_id: int):
    return db.scalars(select(Report).options(joinedload(Report.reporter)).where(Report.target_type == target_type, Report.target_id == target_id, Report.status == "open").order_by(Report.id.desc())).all()


def _author(db: Session, target_type: str, target_id: int):
    target = moderation.get_target(db, target_type, target_id)
    if not target:
        return None
    author_id = getattr(target, "author_id", None) or getattr(target, "created_by", None)
    return db.get(User, author_id) if author_id else (target if target_type == "user" else None)


def _action_status(action: str) -> str | None:
    return {"hide": "hidden", "restore": "visible", "delete": "deleted"}.get(action)


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    counters = {
        "reports": int(db.scalar(select(func.count()).select_from(Report).where(Report.status == "open")) or 0),
        "quotes": int(db.scalar(select(func.count()).select_from(Quote).where(Quote.status == "pending")) or 0),
        "classes": int(db.scalar(select(func.count()).select_from(SchoolClass).where(SchoolClass.status == "pending")) or 0),
        "takedowns": int(db.scalar(select(func.count()).select_from(TakedownRequest).where(TakedownRequest.status == "open")) or 0),
        "users": int(db.scalar(select(func.count()).select_from(User)) or 0),
        "banned": int(db.scalar(select(func.count()).select_from(User).where(User.status == "banned")) or 0),
    }
    return render(request, "admin/dashboard.html", counters=counters)


@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    rows = db.execute(
        select(Report.target_type, Report.target_id, func.count().label("count"), func.max(Report.id).label("latest"))
        .where(Report.status == "open")
        .group_by(Report.target_type, Report.target_id)
        .order_by(func.max(Report.id).desc())
    ).all()
    groups = []
    for target_type, target_id, count, latest in rows:
        reports_for = _reports_for_target(db, target_type, target_id)
        groups.append({"target_type": target_type, "target_id": target_id, "count": count, "reports": reports_for, "target": moderation.get_target(db, target_type, target_id), "author": _author(db, target_type, target_id)})
    return render(request, "admin/reports.html", groups=groups)


@router.post("/reports/{target_type}/{target_id}/resolve", response_class=HTMLResponse)
def resolve_report(
    target_type: str,
    target_id: int,
    action: str = Form(...),
    ban_content: str | None = Form(None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_mod),
):
    if action not in {"hide", "restore", "delete", "dismiss", "ban_author"}:
        return HTMLResponse("Neplatná akce.", status_code=400)
    target = moderation.get_target(db, target_type, target_id)
    if not target:
        return HTMLResponse("Cíl nebyl nalezen.", status_code=404)
    reports_for = _reports_for_target(db, target_type, target_id)
    if action == "ban_author":
        author = _author(db, target_type, target_id)
        if not author:
            return HTMLResponse("Autor nebyl nalezen.", status_code=404)
        if author.id == actor.id or author.role == "admin":
            return HTMLResponse("Moderátor nemůže zablokovat sebe ani administrátora.", status_code=403)
        author.status = "banned"
        sessions = db.scalars(select(UserSession).where(UserSession.user_id == author.id)).all()
        for session in sessions:
            db.delete(session)
        if ban_content:
            for model in (Meme, Quote, Resource):
                content = db.scalars(select(model).where(model.author_id == author.id, model.status != "deleted")).all()
                for item in content:
                    item.status = "hidden"
        audit.log(db, actor.id, "ban_author", target_type, target_id, {"hide_content": bool(ban_content)})
    else:
        status = _action_status(action)
        if status:
            if target_type == "class" and status == "visible":
                status = "active"
            moderation.set_status(db, target_type, target_id, status, actor.id, action)
        audit.log(db, actor.id, f"report_{action}", target_type, target_id)

    for report in reports_for:
        report.status = "dismissed" if action == "dismiss" else "actioned"
        report.handled_by = actor.id
        report.handled_at = datetime.now(timezone.utc)
    db.commit()
    return HTMLResponse("Vyřešeno.")


@router.get("/quotes", response_class=HTMLResponse)
def pending_quotes(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    rows = db.scalars(select(Quote).options(joinedload(Quote.author)).where(Quote.status == "pending").order_by(Quote.id.desc())).all()
    return render(request, "admin/quotes.html", quotes=rows)


@router.post("/quotes/{quote_id}/approve")
def approve_quote(quote_id: int, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    quote = db.get(Quote, quote_id)
    if not quote or quote.status != "pending":
        return HTMLResponse("Citát nebyl nalezen.", status_code=404)
    quote.status = "visible"
    audit.log(db, actor.id, "approve_quote", "quote", quote.id)
    db.commit()
    return RedirectResponse("/admin/quotes", status_code=303)


@router.post("/quotes/{quote_id}/reject")
def reject_quote(quote_id: int, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    quote = db.get(Quote, quote_id)
    if not quote or quote.status != "pending":
        return HTMLResponse("Citát nebyl nalezen.", status_code=404)
    quote.status = "deleted"
    audit.log(db, actor.id, "reject_quote", "quote", quote.id)
    db.commit()
    return RedirectResponse("/admin/quotes", status_code=303)


@router.get("/classes", response_class=HTMLResponse)
def pending_classes(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    rows = db.scalars(select(SchoolClass).where(SchoolClass.status.in_(["pending", "hidden"])).order_by(SchoolClass.id.desc())).all()
    return render(request, "admin/classes.html", classes=rows)


@router.post("/classes/{class_id}/approve")
def approve_class(class_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    item = db.get(SchoolClass, class_id)
    if not item:
        return HTMLResponse("Třída nebyla nalezena.", status_code=404)
    item.status = "active"
    audit.log(db, actor.id, "approve_class", "class", class_id)
    db.commit()
    return RedirectResponse("/admin/classes", status_code=303)


@router.post("/classes/{class_id}/hide")
def hide_class(class_id: int, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    item = db.get(SchoolClass, class_id)
    if not item:
        return HTMLResponse("Třída nebyla nalezena.", status_code=404)
    item.status = "hidden"
    audit.log(db, actor.id, "hide_class", "class", class_id)
    db.commit()
    return RedirectResponse("/admin/classes", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def users(request: Request, q: str = "", page: int = 1, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    page = _page(page)
    stmt = select(User).order_by(User.id.desc())
    if q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(needle), User.display_name.ilike(needle)))
    rows = db.scalars(stmt.offset((page - 1) * 50).limit(50)).all()
    return render(request, "admin/users.html", users=rows, query=q, page=page)


@router.post("/users/{user_id}/ban")
def ban_user(user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    target = db.get(User, user_id)
    if not target:
        return HTMLResponse("Uživatel nebyl nalezen.", status_code=404)
    if target.id == actor.id or target.role == "admin":
        return HTMLResponse("Tuto akci nelze provést.", status_code=403)
    target.status = "banned"
    for session in db.scalars(select(UserSession).where(UserSession.user_id == target.id)).all():
        db.delete(session)
    audit.log(db, actor.id, "ban_user", "user", target.id)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    target = db.get(User, user_id)
    if not target:
        return HTMLResponse("Uživatel nebyl nalezen.", status_code=404)
    target.status = "active"
    audit.log(db, actor.id, "unban_user", "user", target.id)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/role")
def change_role(user_id: int, role: str = Form(...), db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if role not in {"student", "teacher", "moderator", "admin"}:
        return HTMLResponse("Neplatná role.", status_code=400)
    target = db.get(User, user_id)
    if not target:
        return HTMLResponse("Uživatel nebyl nalezen.", status_code=404)
    if target.role == "admin" and role != "admin":
        admins = int(db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.status != "deleted")) or 0)
        if admins <= 1:
            return HTMLResponse("Posledního administrátora nelze demotovat.", status_code=409)
    target.role = role
    audit.log(db, actor.id, "change_role", "user", target.id, {"role": role})
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, page: int = 1, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    page = _page(page)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset((page - 1) * 50).limit(50)).all()
    return render(request, "admin/audit.html", entries=rows, page=page)


@router.get("/takedowns", response_class=HTMLResponse)
def takedowns(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    rows = db.scalars(select(TakedownRequest).order_by(TakedownRequest.id.desc())).all()
    return render(request, "admin/takedowns.html", takedowns=rows)


@router.post("/takedowns/{request_id}/done")
def done_takedown(request_id: int, db: Session = Depends(get_db), actor: User = Depends(require_mod)):
    item = db.get(TakedownRequest, request_id)
    if not item:
        return HTMLResponse("Požadavek nebyl nalezen.", status_code=404)
    item.status = "done"
    item.handled_by = actor.id
    audit.log(db, actor.id, "takedown_done", "takedown", item.id)
    db.commit()
    return RedirectResponse("/admin/takedowns", status_code=303)
