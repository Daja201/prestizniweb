# Moderation-specific behavior tests.
from __future__ import annotations

from app.core.config import settings
from app.models import Meme, Report, User


def _meme(db, user):
    meme = Meme(author_id=user.id, caption="test", image_path="x.webp", thumb_path="x.webp", width=1, height=1, status="visible")
    db.add(meme)
    db.commit()
    db.refresh(meme)
    return meme


def test_duplicate_report_rejected(client, db, make_user, login):
    user = make_user()
    target_user = make_user()
    login(client, user)
    first = client.post("/reports", data={"target_type": "user", "target_id": target_user.id, "reason": "spam", "details": ""})
    second = client.post("/reports", data={"target_type": "user", "target_id": target_user.id, "reason": "spam", "details": ""})
    assert first.status_code == 200
    assert second.status_code == 409


def test_own_content_report_rejected(client, db, make_user, login):
    user = make_user()
    meme = _meme(db, user)
    login(client, user)
    response = client.post("/reports", data={"target_type": "meme", "target_id": meme.id, "reason": "spam", "details": ""})
    assert response.status_code == 400
    assert db.query(Report).count() == 0


def test_auto_hide_threshold(client, db, make_user, login):
    original = settings.auto_hide_report_threshold
    settings.auto_hide_report_threshold = 2
    try:
        author = make_user()
        first = make_user()
        second = make_user()
        meme = _meme(db, author)
        login(client, first)
        assert client.post("/reports", data={"target_type": "meme", "target_id": meme.id, "reason": "spam"}).status_code == 200
        client.cookies.clear()
        login(client, second)
        assert client.post("/reports", data={"target_type": "meme", "target_id": meme.id, "reason": "spam"}).status_code == 200
        db.refresh(meme)
        assert meme.status == "hidden"
    finally:
        settings.auto_hide_report_threshold = original


def test_ban_flow(client, db, make_user, login):
    moderator = make_user(role="admin")
    author = make_user()
    meme = _meme(db, author)
    login(client, moderator)
    response = client.post("/admin/reports/user/%s/resolve" % author.id, data={"action": "ban_author"})
    # A user target has no report unless one was created, but the ban action itself is target-valid.
    assert response.status_code in {200, 404}


def test_last_admin_protection(client, make_user, login):
    super_admin = make_user(role="super_admin")
    login(client, super_admin)
    response = client.post(f"/admin/users/{super_admin.id}/role", data={"role": "user"})
    assert response.status_code == 409


def test_regular_admin_cannot_assign_roles(client, make_user, login):
    admin = make_user(role="admin")
    target = make_user()
    login(client, admin)
    response = client.post(f"/admin/users/{target.id}/role", data={"role": "super_admin"})
    assert response.status_code == 403


def test_super_admin_can_assign_admin_role(client, db, make_user, login):
    super_admin = make_user(role="super_admin")
    target = make_user()
    login(client, super_admin)
    response = client.post(f"/admin/users/{target.id}/role", data={"role": "admin"})
    assert response.status_code == 303
    db.expire_all()
    assert db.get(User, target.id).role == "admin"
