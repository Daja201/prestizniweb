# Class profile routes, memberships, and class creation workflow.
from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.db import get_db
from app.core.deps import require_mod, require_user
from app.core.flash import flash
from app.core.ratelimit import rate_limit
from app.core.templates import render
from app.models import ClassMember, Meme, Quote, Resource, SchoolClass, User

router = APIRouter()


def _slugify(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:40]


def _unique_slug(db: Session, base: str) -> str:
    base = (base or "trida")[:40]
    candidate = base
    index = 2
    while db.scalar(select(SchoolClass.id).where(SchoolClass.slug == candidate)) is not None:
        suffix = f"-{index}"
        candidate = f"{base[:40-len(suffix)]}{suffix}"
        index += 1
    return candidate


def _membership_count(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.user_id == user_id, ClassMember.status == "approved")) or 0)


def _visible_class(db: Session, slug: str, user: User | None):
    item = db.scalar(select(SchoolClass).where(SchoolClass.slug == slug))
    if not item:
        return None
    if item.status == "active":
        return item
    if user and (user.role in {"moderator", "admin"} or item.created_by == user.id):
        return item
    return None


@router.get("/classes", response_class=HTMLResponse)
def classes(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = db.scalars(select(SchoolClass).where(SchoolClass.status == "active").order_by(SchoolClass.name)).all()
    counts = dict(db.execute(select(ClassMember.class_id, func.count()).where(ClassMember.status == "approved").group_by(ClassMember.class_id)).all())
    return render(request, "classes/list.html", classes=rows, member_counts=counts)


@router.get("/classes/new", response_class=HTMLResponse)
def new_class(request: Request, user: User = Depends(require_user)):
    return render(request, "classes/new.html")


@router.post("/classes", response_class=HTMLResponse, dependencies=[Depends(rate_limit("class_create", 3, 86400))])
def create_class(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    name, description = name.strip(), description.strip()
    if not 2 <= len(name) <= 60:
        return render(request, "classes/new.html", error="Název musí mít 2–60 znaků.", status_code=400)
    if len(description) > 500:
        return render(request, "classes/new.html", error="Popis může mít nejvýše 500 znaků.", status_code=400)
    if _membership_count(db, user.id) >= 3:
        return render(request, "classes/new.html", error="Můžeš být členem nejvýše 3 schválených tříd.", status_code=400)
    slug = _unique_slug(db, _slugify(name))
    if not re.fullmatch(r"[a-z0-9-]{2,40}", slug):
        return render(request, "classes/new.html", error="Z názvu nelze vytvořit platný profil třídy.", status_code=400)
    item = SchoolClass(name=name, slug=slug, description=description, created_by=user.id, status="pending")
    db.add(item)
    db.flush()
    db.add(ClassMember(class_id=item.id, user_id=user.id, role="owner", status="approved"))
    db.commit()
    response = request.app.state  # keep handler independent from response internals
    from fastapi.responses import RedirectResponse
    result = RedirectResponse(f"/c/{slug}", status_code=303)
    flash(result, "Profil třídy byl odeslán ke schválení.", "success")
    return result


@router.get("/c/{slug}", response_class=HTMLResponse)
def class_detail(request: Request, slug: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    item = _visible_class(db, slug, user)
    if not item:
        return render(request, "errors/404.html", status_code=404)
    members = db.scalars(
        select(ClassMember).options(joinedload(ClassMember.user)).where(ClassMember.class_id == item.id, ClassMember.status == "approved").order_by(ClassMember.created_at)
    ).all()
    memes = db.scalars(select(Meme).where(Meme.class_id == item.id, Meme.status == "visible").order_by(Meme.id.desc()).limit(12)).all()
    quotes = db.scalars(select(Quote).where(Quote.class_id == item.id, Quote.status == "visible").order_by(Quote.id.desc()).limit(12)).all()
    resources = db.scalars(select(Resource).where(Resource.class_id == item.id, Resource.status == "visible").order_by(Resource.id.desc()).limit(12)).all()
    count = len(members)
    is_owner = item.created_by == user.id
    return render(request, "classes/detail.html", school_class=item, members=members, member_count=count, memes=memes, quotes=quotes, resources=resources, is_owner=is_owner)


@router.post("/c/{slug}/join", response_class=HTMLResponse)
def join_class(request: Request, slug: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    item = db.scalar(select(SchoolClass).where(SchoolClass.slug == slug, SchoolClass.status == "active"))
    if not item:
        return HTMLResponse("Třída nebyla nalezena.", status_code=404)
    if _membership_count(db, user.id) >= 3:
        return HTMLResponse("Můžeš být členem nejvýše 3 schválených tříd.", status_code=400)
    existing = db.get(ClassMember, (item.id, user.id))
    if existing:
        return HTMLResponse("O členství už bylo požádáno.", status_code=409)
    db.add(ClassMember(class_id=item.id, user_id=user.id, role="member", status="pending"))
    db.commit()
    return HTMLResponse("Žádost o členství byla odeslána.")


def _can_manage(item: SchoolClass, actor: User) -> bool:
    return actor.role in {"moderator", "admin"} or item.created_by == actor.id


@router.post("/c/{slug}/members/{user_id}/approve", response_class=HTMLResponse)
def approve_member(slug: str, user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_user)):
    item = db.scalar(select(SchoolClass).where(SchoolClass.slug == slug))
    membership = db.get(ClassMember, (item.id, user_id)) if item else None
    if not item or not membership or not _can_manage(item, actor):
        return HTMLResponse("Nemáš oprávnění.", status_code=403)
    if _membership_count(db, user_id) >= 3 and membership.status != "approved":
        return HTMLResponse("Uživatel už má 3 schválená členství.", status_code=400)
    membership.status = "approved"
    db.commit()
    return HTMLResponse("Členství schváleno.")


@router.post("/c/{slug}/members/{user_id}/remove", response_class=HTMLResponse)
def remove_member(slug: str, user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_user)):
    item = db.scalar(select(SchoolClass).where(SchoolClass.slug == slug))
    membership = db.get(ClassMember, (item.id, user_id)) if item else None
    if not item or not membership:
        return HTMLResponse("Členství nebylo nalezeno.", status_code=404)
    if user_id != actor.id and not _can_manage(item, actor):
        return HTMLResponse("Nemáš oprávnění.", status_code=403)
    if membership.role == "owner" and user_id == item.created_by:
        return HTMLResponse("Vlastník nemůže sám sebe odebrat.", status_code=400)
    db.delete(membership)
    db.commit()
    return HTMLResponse("Členství odebráno.")


@router.post("/c/{slug}/edit", response_class=HTMLResponse)
def edit_class(slug: str, description: str = Form(...), db: Session = Depends(get_db), actor: User = Depends(require_user)):
    item = db.scalar(select(SchoolClass).where(SchoolClass.slug == slug))
    if not item or item.created_by != actor.id:
        return HTMLResponse("Nemáš oprávnění.", status_code=403)
    description = description.strip()
    if len(description) > 500:
        return HTMLResponse("Popis může mít nejvýše 500 znaků.", status_code=400)
    item.description = description
    db.commit()
    return HTMLResponse("Popis byl uložen.")
