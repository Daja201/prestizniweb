# Covers quote validation, approval visibility, voting, deletion, and diacritic-insensitive search.
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.models import Quote


def _quote_data(**overrides):
    data = {
        "text": "Tohle je testovací citát.",
        "said_by": "p. uč. Novák",
        "context": "test",
        "said_on": date.today().isoformat(),
        "class_id": "",
    }
    data.update(overrides)
    return data


def test_quote_validation_rejects_short_text(client, db, make_user, login):
    user = make_user()
    login(client, user)
    response = client.post(
        "/quotes",
        data=_quote_data(text="x"),
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "2 až 400" in response.text
    assert db.scalar(select(Quote).where(Quote.author_id == user.id)) is None


def test_quote_pending_flow_and_author_visibility(client, db, make_user, login, monkeypatch):
    monkeypatch.setattr(settings, "quotes_require_approval", True)
    author = make_user()
    other = make_user()

    login(client, author)
    response = client.post("/quotes", data=_quote_data(), follow_redirects=False)
    assert response.status_code == 303
    quote = db.scalar(select(Quote).where(Quote.author_id == author.id))
    assert quote is not None
    assert quote.status == "pending"

    response = client.get("/quotes")
    assert response.status_code == 200
    assert "Tohle je testovací citát." in response.text
    assert "čeká na schválení" in response.text

    login(client, other)
    response = client.get("/quotes")
    assert response.status_code == 200
    assert "Tohle je testovací citát." not in response.text


def test_quote_vote_toggle_updates_counter(client, db, make_user, login, monkeypatch):
    monkeypatch.setattr(settings, "quotes_require_approval", False)
    user = make_user()
    quote = Quote(
        author_id=user.id,
        text="Vote test",
        said_by="student",
        context="",
        status="visible",
        votes_count=0,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    login(client, user)

    response = client.post(f"/quotes/{quote.id}/vote")
    assert response.status_code == 200
    db.refresh(quote)
    assert quote.votes_count == 1
    assert "Hlasováno" in response.text

    response = client.post(f"/quotes/{quote.id}/vote")
    assert response.status_code == 200
    db.refresh(quote)
    assert quote.votes_count == 0
    assert "Hlasováno" not in response.text


def test_quote_search_ignores_diacritics(client, db, make_user, login, monkeypatch):
    monkeypatch.setattr(settings, "quotes_require_approval", False)
    user = make_user()
    quote = Quote(
        author_id=user.id,
        text="Dnes jsme řešili žlutá auta.",
        said_by="učitel",
        context="",
        status="visible",
        votes_count=0,
    )
    db.add(quote)
    db.commit()
    login(client, user)

    response = client.get("/quotes?q=zluta")
    assert response.status_code == 200
    assert "žlutá auta" in response.text


def test_quote_delete_is_author_only(client, db, make_user, login, monkeypatch):
    monkeypatch.setattr(settings, "quotes_require_approval", False)
    author = make_user()
    other = make_user()
    quote = Quote(
        author_id=author.id,
        text="Smazat mě",
        said_by="student",
        status="visible",
        votes_count=0,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)

    login(client, other)
    response = client.post(f"/quotes/{quote.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    db.refresh(quote)
    assert quote.status == "visible"

    login(client, author)
    response = client.post(f"/quotes/{quote.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    db.refresh(quote)
    assert quote.status == "deleted"