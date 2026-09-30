# Serves the public landing page and the signed-in home dashboard.
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.core.deps import current_user
from app.core.templates import render
from app.models import Meme, Quote, User

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    if user is None:
        return render(request, "home.html")

    memes = list(
        db.scalars(
            select(Meme)
            .options(selectinload(Meme.author))
            .where(Meme.status == "visible")
            .order_by(desc(Meme.id))
            .limit(8)
        ).all()
    )
    quotes = list(
        db.scalars(
            select(Quote)
            .options(selectinload(Quote.author))
            .where(Quote.status == "visible")
            .order_by(desc(Quote.id))
            .limit(5)
        ).all()
    )
    return render(request, "home.html", memes=memes, quotes=quotes)