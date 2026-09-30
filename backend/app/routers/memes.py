# Provides the meme feed, image uploads, detail view, likes, and author deletion.
from __future__ import annotations

import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import require_user
from app.core.flash import flash
from app.core.ratelimit import rate_limit
from app.core.storage import delete as delete_storage, save_bytes
from app.core.templates import render
from app.models import ClassMember, Meme, MemeLike, SchoolClass, Tag, User
from app.services.images import process_image

router = APIRouter()
_TAG_RE = re.compile(r"^[a-z0-9áčďéěíňóřšťúůýž_-]{2,30}$")


def _parse_tags(raw: str) -> list[str]:
    values = re.split(r"[,\s]+", raw.strip().lower()) if raw.strip() else []
    result: list[str] = []
    for value in values:
        if not value:
            continue
        if not _TAG_RE.fullmatch(value):
            raise ValueError("Tag may contain letters, numbers, hyphens and underscores (2–30 characters).")
        if value not in result:
            result.append(value)
    if len(result) > 5:
        raise ValueError("You can add at most 5 tags.")
    return result


def _can_open_hidden(user: User) -> bool:
    return user.role in {"admin", "super_admin"}


def _get_meme(db: Session, meme_id: int, user: User) -> Meme | None:
    meme = db.scalar(
        select(Meme)
        .options(selectinload(Meme.author), selectinload(Meme.tags), selectinload(Meme.school_class))
        .where(Meme.id == meme_id, Meme.status != "deleted")
    )
    if meme is None or (meme.status == "hidden" and not _can_open_hidden(user)):
        return None
    return meme


def _feed_url(before: int | None, tag: str | None, class_slug: str | None, sort: str, limit: int) -> str | None:
    if before is None:
        return None
    params: list[tuple[str, str]] = [("before", str(before)), ("limit", str(limit))]
    if tag:
        params.append(("tag", tag))
    if class_slug:
        params.append(("class", class_slug))
    if sort != "new":
        params.append(("sort", sort))
    return "/memes?" + urlencode(params)


def _feed_data(db: Session, user: User, tag: str | None, class_slug: str | None, sort: str, before: int | None, limit: int):
    statuses = ["visible", "hidden"] if _can_open_hidden(user) else ["visible"]
    statement = (
        select(Meme)
        .options(selectinload(Meme.author), selectinload(Meme.tags))
        .where(Meme.status.in_(statuses))
    )
    if before is not None:
        statement = statement.where(Meme.id < before)
    if tag:
        statement = statement.where(Meme.tags.any(Tag.name == tag))
    if class_slug:
        statement = statement.join(Meme.school_class).where(
            SchoolClass.slug == class_slug,
            SchoolClass.status == "active",
        )
    if sort == "popular":
        statement = statement.order_by(desc(Meme.likes_count), desc(Meme.id))
    else:
        statement = statement.order_by(desc(Meme.created_at), desc(Meme.id))
    statement = statement.limit(limit + 1)
    rows = list(db.scalars(statement).all())
    has_more = len(rows) > limit
    memes = rows[:limit]
    next_url = _feed_url(memes[-1].id, tag, class_slug, sort, limit) if has_more and memes else None
    voted_ids = set()
    if memes:
        voted_ids = set(db.scalars(
            select(MemeLike.meme_id).where(
                MemeLike.user_id == user.id,
                MemeLike.meme_id.in_([meme.id for meme in memes]),
            )
        ).all())
    return memes, voted_ids, next_url


@router.get("/memes", response_class=HTMLResponse)
def list_memes(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    before: int | None = Query(None, ge=1),
    limit: int = Query(24, ge=1, le=60),
    tag: str | None = Query(None, max_length=30),
    class_filter: str | None = Query(None, alias="class", max_length=40),
    sort: str = Query("new", max_length=20),
):
    tag_name = tag.strip().lower() if tag and tag.strip() else None
    class_slug = class_filter.strip() if class_filter and class_filter.strip() else None
    sort = sort if sort in {"new", "popular"} else "new"
    memes, voted_ids, next_url = _feed_data(db, user, tag_name, class_slug, sort, before, limit)
    context = {"memes": memes, "voted_ids": voted_ids, "next_url": next_url, "tag": tag_name or "", "class_slug": class_slug or "", "sort": sort}
    if request.headers.get("HX-Request") == "true":
        return render(request, "memes/_items.html", **context)
    return render(request, "memes/feed.html", **context)


@router.get("/memes/new", response_class=HTMLResponse)
def new_meme(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    classes = list(db.scalars(
        select(SchoolClass)
        .join(ClassMember, ClassMember.class_id == SchoolClass.id)
        .where(SchoolClass.status == "active", ClassMember.user_id == user.id, ClassMember.status == "approved")
        .order_by(SchoolClass.name)
    ).all())
    return render(request, "memes/new.html", classes=classes, form={}, error=None)


@router.post("/memes", dependencies=[Depends(rate_limit("meme-upload", 10, 3600))])
def create_meme(
    request: Request,
    image: UploadFile = File(...),
    caption: str = Form(""),
    tags: str = Form(""),
    class_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    clean_caption = caption.strip()
    try:
        if len(clean_caption) > 300:
            raise ValueError("Caption may be at most 300 characters.")
        tag_names = _parse_tags(tags)
        processed = process_image(image.file.read(settings.max_image_mb * 1024 * 1024 + 1))
        parsed_class_id = int(class_id) if class_id.strip() else None
        if parsed_class_id is not None:
            class_allowed = db.scalar(
                select(SchoolClass.id)
                .join(ClassMember, ClassMember.class_id == SchoolClass.id)
                .where(
                    SchoolClass.id == parsed_class_id,
                    SchoolClass.status == "active",
                    ClassMember.user_id == user.id,
                    ClassMember.status == "approved",
                )
            )
            if class_allowed is None:
                raise ValueError("The class must be active and you must be an approved member.")
    except (ValueError, OSError) as exc:
        classes = list(db.scalars(
            select(SchoolClass)
            .join(ClassMember, ClassMember.class_id == SchoolClass.id)
            .where(SchoolClass.status == "active", ClassMember.user_id == user.id, ClassMember.status == "approved")
            .order_by(SchoolClass.name)
        ).all())
        return render(request, "memes/new.html", 422, classes=classes, form={"caption": caption, "tags": tags, "class_id": class_id}, error=str(exc))

    image_path: str | None = None
    thumb_path: str | None = None
    try:
        image_path = save_bytes("memes", processed.image_bytes, "webp")
        thumb_path = save_bytes("memes", processed.thumb_bytes, "webp")
        meme = Meme(
            author_id=user.id,
            class_id=parsed_class_id,
            caption=clean_caption,
            image_path=image_path,
            thumb_path=thumb_path,
            width=processed.width,
            height=processed.height,
            status="visible",
        )
        db.add(meme)
        db.flush()
        for tag_name in tag_names:
            tag = db.scalar(select(Tag).where(Tag.name == tag_name))
            if tag is None:
                tag = Tag(name=tag_name)
                db.add(tag)
                db.flush()
            meme.tags.append(tag)
        db.commit()
    except Exception:
        db.rollback()
        delete_storage(image_path)
        delete_storage(thumb_path)
        raise

    response = RedirectResponse(f"/memes/{meme.id}", status_code=303)
    flash(response, "Meme has been added.", "success")
    return response


@router.get("/memes/{meme_id}", response_class=HTMLResponse)
def meme_detail(
    request: Request,
    meme_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    meme = _get_meme(db, meme_id, user)
    if meme is None:
        return render(request, "errors/404.html", status_code=404)
    liked = db.scalar(select(MemeLike.meme_id).where(MemeLike.meme_id == meme.id, MemeLike.user_id == user.id)) is not None
    return render(request, "memes/detail.html", meme=meme, liked=liked)


@router.post("/memes/{meme_id}/like", response_class=HTMLResponse, dependencies=[Depends(rate_limit("meme-like", 120, 60))])
def toggle_meme_like(
    request: Request,
    meme_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    meme = db.scalar(select(Meme).where(Meme.id == meme_id, Meme.status == "visible"))
    if meme is None:
        return render(request, "errors/404.html", status_code=404)
    removed_id = db.scalar(
        delete(MemeLike)
        .where(MemeLike.meme_id == meme_id, MemeLike.user_id == user.id)
        .returning(MemeLike.meme_id)
    )
    if removed_id is not None:
        db.execute(update(Meme).where(Meme.id == meme_id).values(likes_count=func.greatest(Meme.likes_count - 1, 0)))
        liked = False
    else:
        inserted_id = db.scalar(
            pg_insert(MemeLike)
            .values(meme_id=meme_id, user_id=user.id)
            .on_conflict_do_nothing(index_elements=[MemeLike.meme_id, MemeLike.user_id])
            .returning(MemeLike.meme_id)
        )
        if inserted_id is not None:
            db.execute(update(Meme).where(Meme.id == meme_id).values(likes_count=Meme.likes_count + 1))
        liked = True
    db.commit()
    db.refresh(meme)
    return render(request, "memes/_like_button.html", meme=meme, liked=liked)


@router.post("/memes/{meme_id}/delete")
def delete_meme(
    meme_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    meme = db.scalar(select(Meme).where(Meme.id == meme_id, Meme.status != "deleted"))
    if meme is None or meme.author_id != user.id:
        response = RedirectResponse("/memes", status_code=303)
        flash(response, "Meme not found or you cannot delete it.", "error")
        return response
    image_path, thumb_path = meme.image_path, meme.thumb_path
    meme.status = "deleted"
    db.commit()
    delete_storage(image_path)
    delete_storage(thumb_path)
    response = RedirectResponse("/memes", status_code=303)
    flash(response, "Meme has been deleted.", "success")
    return response