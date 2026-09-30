# Integration smoke tests for the complete merged application.
from __future__ import annotations

from io import BytesIO

from PIL import Image

import pytest


PUBLIC = ["/", "/login", "/rules", "/privacy", "/takedown", "/healthz"]
PRIVATE = [
    "/memes", "/memes/new", "/quotes", "/quotes/new", "/resources", "/resources/new",
    "/classes", "/classes/new", "/me", "/admin", "/admin/reports", "/admin/quotes",
    "/admin/classes", "/admin/users", "/admin/audit", "/admin/takedowns",
]


def test_public_routes(client):
    for path in PUBLIC:
        response = client.get(path)
        if path == "/":
            assert response.status_code == 303
            assert response.headers["location"] == "/login"
            continue
        assert response.status_code == 200, path


def test_private_routes_redirect_anonymous(client):
    for path in PRIVATE:
        response = client.get(path)
        assert response.status_code in {303, 307}, (path, response.status_code, response.text[:200])
        assert "/login" in response.headers.get("location", "")


def test_user_admin_super_admin_get_routes(client, make_user, login):
    for role in ("user", "admin", "super_admin"):
        user = make_user(role=role)
        login(client, user)
        for path in PRIVATE:
            response = client.get(path)
            assert response.status_code != 500, (role, path, response.text[:500])
        client.cookies.clear()


def test_full_content_journey(client, make_user, login):
    student = make_user()
    moderator = make_user(role="admin")
    login(client, student)

    image = BytesIO()
    Image.new("RGB", (4, 4), (255, 255, 255)).save(image, format="JPEG")
    image.seek(0)
    meme = client.post(
        "/memes",
        data={"caption": "Testovací meme", "class_id": ""},
        files={"image": ("test.jpg", image, "image/jpeg")},
    )
    assert meme.status_code == 303, meme.text

    quote = client.post("/quotes", data={"text": "Bezpečný testovací citát", "said_by": "test", "context": "", "class_id": ""})
    assert quote.status_code == 303, quote.text

    resource = client.post(
        "/resources",
        data={"title": "Test", "description": "", "subject": "Matematika", "kind": "link", "url": "https://example.invalid/test", "class_id": ""},
    )
    assert resource.status_code == 303, resource.text

    from app.models import Meme, Quote, Resource
    db = __import__("app.core.db", fromlist=["SessionLocal"]).SessionLocal()
    try:
        targets = [("meme", db.query(Meme).order_by(Meme.id.desc()).first()), ("quote", db.query(Quote).order_by(Quote.id.desc()).first()), ("resource", db.query(Resource).order_by(Resource.id.desc()).first())]
    finally:
        db.close()

    for target_type, target in targets:
        assert target is not None
        report = client.post("/reports", data={"target_type": target_type, "target_id": target.id, "reason": "spam"})
        assert report.status_code == 200

    client.cookies.clear()
    login(client, moderator)
    for target_type, target in targets:
        response = client.post(f"/admin/reports/{target_type}/{target.id}/resolve", data={"action": "hide"})
        assert response.status_code == 200
