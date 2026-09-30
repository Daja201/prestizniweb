# Serves the public landing page; signed-in users are sent straight to /me.
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user
from app.models import User

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    return RedirectResponse("/me", status_code=303)
