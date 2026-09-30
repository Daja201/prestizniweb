# Public community rules, privacy information, and takedown request handling.
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import rate_limit
from app.core.templates import render
from app.models import TakedownRequest

router = APIRouter()


@router.get("/rules", response_class=HTMLResponse)
def rules(request: Request):
    return render(request, "legal/rules.html")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "legal/privacy.html", contact_email=settings.contact_email)


@router.get("/takedown", response_class=HTMLResponse)
def takedown_form(request: Request):
    return render(request, "legal/takedown.html")


@router.post("/takedown", response_class=HTMLResponse, dependencies=[Depends(rate_limit("takedown", 3, 3600))])
def takedown(
    request: Request,
    name: str = Form(...),
    contact: str = Form(...),
    target_url: str = Form(...),
    message: str = Form(...),
    db: Session = Depends(get_db),
):
    name, contact, target_url, message = name.strip(), contact.strip(), target_url.strip(), message.strip()
    errors = []
    if not 1 <= len(name) <= 100:
        errors.append("Name must be 1–100 characters.")
    if not 1 <= len(contact) <= 200:
        errors.append("Contact must be 1–200 characters.")
    if not 1 <= len(target_url) <= 500:
        errors.append("URL must be 1–500 characters.")
    if not 1 <= len(message) <= 2000:
        errors.append("Message must be 1–2000 characters.")
    if errors:
        return render(request, "legal/takedown.html", error=" ".join(errors), status_code=400)
    db.add(TakedownRequest(name=name, contact=contact, target_url=target_url, message=message))
    db.commit()
    return render(request, "legal/takedown_done.html")
