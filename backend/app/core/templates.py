# templates.py - Jinja2 templates, render() helper, Czech-locale filters/globals
import json
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.flash import _COOKIE

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_MONTHS_CS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def cs_date(dt: date | datetime | None) -> str:
    if dt is None:
        return ""
    return f"{dt.day}. {_MONTHS_CS[dt.month - 1]} {dt.year}"


def cs_datetime(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"{cs_date(dt)} {dt.hour:02d}:{dt.minute:02d}"


def _plural_cs(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def timeago(dt: datetime | None) -> str:
    """Relative English time, e.g. '5 minutes ago'."""
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    reference = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    seconds = int((now - reference).total_seconds())

    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''} ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def media_url(rel_path: str | None) -> str:
    if not rel_path:
        return ""
    return f"/media/{rel_path}"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["cs_date"] = cs_date
templates.env.filters["cs_datetime"] = cs_datetime
templates.env.filters["timeago"] = timeago
templates.env.globals["media_url"] = media_url


def _read_flash(request: Request) -> dict | None:
    raw = request.cookies.get(_COOKIE)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or "message" not in data:
        return None
    return data


def render(request: Request, template_name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    """Render a template with the standard shared context (user, settings, flash)."""
    flash_data = _read_flash(request)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        status_code=status_code,
        context={
            "user": getattr(request.state, "user", None),
            "settings": settings,
            "flash": flash_data,
            **ctx,
        },
    )
    if flash_data is not None:
        response.delete_cookie(_COOKIE, path="/")
    return response