# Covers shared rate-limit persistence and adaptive login CAPTCHA escalation.
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import settings
from app.core.ratelimit import get_attempt_count, record_attempt
from app.models import LoginToken
from app.routers import auth


def test_rate_limit_persists_count_and_starts_cooldown(db):
    subject = f"ratelimit-test-{uuid4().hex}"
    for expected in (1, 2):
        hits, blocked_until = record_attempt(db, "test", subject, 2, 3600, 600)
        assert hits == expected
        assert blocked_until is None

    hits, blocked_until = record_attempt(db, "test", subject, 2, 3600, 600)
    assert hits == 3
    assert blocked_until is not None and blocked_until > datetime.now(timezone.utc)
    assert get_attempt_count(db, "test", subject, 3600) == 3


def test_login_turnstile_escalates_after_ip_threshold(client, db, monkeypatch):
    monkeypatch.setattr(settings, "turnstile_site_key", "test-site-key")
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    monkeypatch.setattr(settings, "login_captcha_threshold", 3)
    subject = "ip:testclient"
    for _ in range(3):
        record_attempt(db, "login_ip", subject, 20, 3600, 900)

    page = client.get("/login")
    assert page.status_code == 200
    assert "data-sitekey=\"test-site-key\"" in page.text
    assert "challenges.cloudflare.com/turnstile/v0/api.js" in page.text

    monkeypatch.setattr(auth, "_verify_turnstile", lambda token, request: False)
    response = client.post("/login", data={"email": "person@example.net", "cf-turnstile-response": "invalid"})
    assert response.status_code == 429
    assert db.query(LoginToken).count() == 0


def test_login_route_applies_email_rate_limit(client):
    for _ in range(settings.login_email_rate_limit):
        response = client.post("/login", data={"email": "not-an-email"})
        assert response.status_code == 200

    response = client.post("/login", data={"email": "not-an-email"})
    assert response.status_code == 429