# flash.py - one-shot flash messages carried in a short-lived cookie
import json

from fastapi import Response

_COOKIE = "flash"


def flash(response: Response, message: str, level: str = "info") -> None:
    """Queue a flash message (info|success|error) to be shown on the next page."""
    payload = json.dumps({"message": message, "level": level})
    response.set_cookie(
        _COOKIE,
        payload,
        max_age=30,
        httponly=True,
        samesite="lax",
        path="/",
    )