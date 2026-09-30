# Provides quote listing, submission, voting, and author deletion routes.
from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, delete, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.flash import flash
from app.core.templates import render
from app.core.deps import require_user
from app.core.ratelimit import rate_limit
from app.models import ClassMember, Quote, QuoteVote, SchoolClass, User

router = APIRouter()


def _search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _is_moderator(user: User) -> bool:
    return user.role in {"admin", "super_admin"}


def _quote_filter_for_user(user: User):
    visible_clause = Quote.status == "visible"
    own_pending_clause = and_(Quote.status == "pending", Quote.author_id == user.id)
    moderator_clause = and_(Quote.status == "hidden")
    if _is_moderator(user):
        return and_(Quote.status != "deleted", or_(visible_clause, own_pending_clause, moderator_clause))
    return and_(Quote.status != "deleted", or_(visible_clause, own_pending_clause))


def _quote_list_query(
    user: User,
    search: str | None,
    class_slug: str | None,
    before: int | None,
    limit: int,
):
    stmt = (
        select(Quote)
        .options(selectinload(Quote.author), selectinload(Quote.school_class))
        .where(_quote_filter_for_user(user))
        .order_by(desc(Quote.id))
        .limit(limit + 1)
    )
    if before is not None:
        stmt = stmt.where(Quote.id < before)
    if search:
        pattern = _search_pattern(search.strip())
        searchable = func.unaccent(Quote.text + " " + Quote.said_by)
        stmt = stmt.where(searchable.ilike(func.unaccent(pattern), escape="\\"))
    if class_slug:
        stmt = stmt.join(Quote.school_class).where(
            and_(SchoolClass.slug == class_slug, SchoolClass.status == "active")
        )
    return stmt


def _quote_context_url(search: str | None, class_slug: str | None, before: int | None = None) -> str:
    params: list[tuple[str, str]] = []
    if search:
        params.append(("q", search))
    if class_slug:
        params.append(("class", class_slug))
    if before is not None:
        params.append(("before", str(before)))
    params.append(("limit", "24"))
    return "/quotes?" + urlencode(params)


def _quote_form_context(db: Session, user: User) -> dict[str, object]:
    classes = list(
        db.scalars(
            select(SchoolClass)
            .join(ClassMember, ClassMember.class_id == SchoolClass.id)
            .where(
                SchoolClass.status == "active",
                ClassMember.user_id == user.id,
                ClassMember.status == "approved",
            )
            .order_by(SchoolClass.name.asc())
        ).all()
    )
    return {"classes": classes, "today": date.today()}


def _valid_class_for_user(db: Session, class_id: int, user_id: int) -> SchoolClass | None:
    return db.scalar(
        select(SchoolClass)
        .join(ClassMember, ClassMember.class_id == SchoolClass.id)
        .where(
            SchoolClass.id == class_id,
            SchoolClass.status == "active",
            ClassMember.user_id == user_id,
            ClassMember.status == "approved",
        )
    )


@router.get("/quotes", response_class=HTMLResponse)
def list_quotes(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    q: str | None = Query(None, max_length=100),
    class_filter: str | None = Query(None, alias="class", max_length=40),
    before: int | None = Query(None, ge=1),
    limit: int = Query(24, ge=1, le=60),
):
    search = q.strip() if q and q.strip() else None
    class_slug = class_filter.strip() if class_filter and class_filter.strip() else None

    stmt = _quote_list_query(user, search, class_slug, before, limit)
    rows = list(db.scalars(stmt).all())
    has_more = len(rows) > limit
    quotes = rows[:limit]
    next_before = quotes[-1].id if has_more and quotes else None
    next_url = _quote_context_url(search, class_slug, next_before) if next_before else None
    voted_ids = {
        quote_id
        for quote_id in db.scalars(
            select(QuoteVote.quote_id).where(
                QuoteVote.user_id == user.id,
                QuoteVote.quote_id.in_([quote.id for quote in quotes]),
            )
        ).all()
    } if quotes else set()

    context = {
        "quotes": quotes,
        "q": search or "",
        "class_slug": class_slug or "",
        "next_url": next_url,
        "voted_ids": voted_ids,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "quotes/_items.html", **context)
    classes = list(
        db.scalars(
            select(SchoolClass)
            .where(SchoolClass.status == "active")
            .order_by(SchoolClass.name.asc())
        ).all()
    )
    return render(request, "quotes/list.html", classes=classes, **context)


@router.get("/quotes/new", response_class=HTMLResponse)
def new_quote(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return render(request, "quotes/new.html", **_quote_form_context(db, user), form={}, errors={})


@router.post("/quotes", response_class=HTMLResponse, dependencies=[Depends(rate_limit("quote-create", 10, 3600))])
def create_quote(
    request: Request,
    text: str = Form(...),
    said_by: str = Form(...),
    context: str = Form(""),
    said_on: str = Form(""),
    class_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    form = {
        "text": text,
        "said_by": said_by,
        "context": context,
        "said_on": said_on,
        "class_id": class_id,
    }
    errors: dict[str, str] = {}

    clean_text = text.strip()
    clean_said_by = said_by.strip()
    clean_context = context.strip()
    if not 2 <= len(clean_text) <= 400:
        errors["text"] = "Citát musí mít 2 až 400 znaků."
    if not 1 <= len(clean_said_by) <= 80:
        errors["said_by"] = "Autor výroku musí mít 1 až 80 znaků."
    if len(clean_context) > 200:
        errors["context"] = "Kontext může mít nejvýše 200 znaků."

    parsed_date: date | None = None
    if said_on.strip():
        try:
            parsed_date = date.fromisoformat(said_on.strip())
        except ValueError:
            errors["said_on"] = "Datum není platné."
        else:
            if parsed_date > date.today():
                errors["said_on"] = "Datum nesmí být v budoucnosti."

    parsed_class_id: int | None = None
    if class_id.strip():
        try:
            parsed_class_id = int(class_id)
        except ValueError:
            errors["class_id"] = "Vyberte platnou třídu."
        else:
            if parsed_class_id <= 0 or _valid_class_for_user(db, parsed_class_id, user.id) is None:
                errors["class_id"] = "Třída musí být aktivní a musíte být schváleným členem."

    if errors:
        return render(
            request,
            "quotes/new.html",
            422,
            **_quote_form_context(db, user),
            form=form,
            errors=errors,
        )

    status = "pending" if settings.quotes_require_approval else "visible"
    quote = Quote(
        author_id=user.id,
        class_id=parsed_class_id,
        text=clean_text,
        said_by=clean_said_by,
        context=clean_context,
        said_on=parsed_date,
        status=status,
    )
    db.add(quote)
    db.commit()

    response = RedirectResponse("/quotes", status_code=303)
    if status == "pending":
        flash(response, "Citát byl odeslán a čeká na schválení.", "success")
    else:
        flash(response, "Citát byl zveřejněn.", "success")
    return response


@router.post("/quotes/{quote_id}/vote", response_class=HTMLResponse, dependencies=[Depends(rate_limit("quote-vote", 120, 60))])
def vote_quote(
    request: Request,
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    quote = db.scalar(select(Quote).where(Quote.id == quote_id, Quote.status == "visible"))
    if quote is None:
        return render(request, "errors/404.html", status_code=404)

    removed_id = db.scalar(
        delete(QuoteVote)
        .where(QuoteVote.quote_id == quote.id, QuoteVote.user_id == user.id)
        .returning(QuoteVote.quote_id)
    )
    if removed_id is not None:
        db.execute(
            update(Quote)
            .where(Quote.id == quote.id)
            .values(votes_count=func.greatest(Quote.votes_count - 1, 0))
        )
        voted = False
    else:
        inserted_id = db.scalar(
            pg_insert(QuoteVote)
            .values(quote_id=quote.id, user_id=user.id)
            .on_conflict_do_nothing(index_elements=[QuoteVote.quote_id, QuoteVote.user_id])
            .returning(QuoteVote.quote_id)
        )
        if inserted_id is not None:
            db.execute(
                update(Quote)
                .where(Quote.id == quote.id)
                .values(votes_count=Quote.votes_count + 1)
            )
        voted = True
    db.commit()
    db.refresh(quote)
    return render(request, "quotes/_vote_button.html", quote=quote, user=user, voted=voted)


@router.post("/quotes/{quote_id}/delete")
def delete_quote(
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    quote = db.scalar(select(Quote).where(Quote.id == quote_id))
    if quote is None or quote.status == "deleted":
        response = RedirectResponse("/quotes", status_code=303)
        flash(response, "Citát nebyl nalezen.", "error")
        return response
    if quote.author_id != user.id:
        response = RedirectResponse("/quotes", status_code=303)
        flash(response, "Tento citát můžete odstranit jen vy.", "error")
        return response

    quote.status = "deleted"
    db.commit()
    response = RedirectResponse("/quotes", status_code=303)
    flash(response, "Citát byl odstraněn.", "success")
    return response