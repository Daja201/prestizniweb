# Covers resource upload sniffing, source validation, filtering, downloads, and visibility counters.
from __future__ import annotations

from sqlalchemy import select

from app.models import Resource, Tag
from app.core.storage import save_bytes


def _resource_data(**overrides):
    data = {
        "title": "Testovací materiál",
        "description": "Popis testu",
        "subject": "Matematika",
        "school_year": "2",
        "kind": "notes",
        "tags": "maturita, algebra",
        "class_id": "",
        "url": "https://example.com/material",
    }
    data.update(overrides)
    return data


def _post_file(client, filename, content, **data):
    payload = _resource_data(**data)
    payload["url"] = ""
    return client.post(
        "/resources",
        data=payload,
        files={"file": (filename, content, "application/octet-stream")},
        follow_redirects=False,
    )


def test_resource_accepts_real_pdf_and_png_signatures(client, db, make_user, login):
    user = make_user()
    login(client, user)

    pdf_response = _post_file(client, "notes.pdf", b"%PDF-1.7\n")
    assert pdf_response.status_code == 303
    png_response = _post_file(client, "image.png", b"\x89PNG\r\n\x1a\n")
    assert png_response.status_code == 303
    assert db.scalar(select(Resource).where(Resource.file_name == "notes.pdf")) is not None
    assert db.scalar(select(Resource).where(Resource.file_name == "image.png")) is not None


def test_resource_rejects_renamed_executable_and_html(client, db, make_user, login):
    user = make_user()
    login(client, user)

    exe_response = _post_file(client, "payload.png", b"MZ\x90\x00not-an-image")
    assert exe_response.status_code == 422
    assert "Obsah souboru" in exe_response.text

    html_response = _post_file(client, "page.txt", b"<!doctype html><html><script>alert(1)</script>")
    assert html_response.status_code == 422
    assert "HTML" in html_response.text or "skripty" in html_response.text
    assert db.scalar(select(Resource).where(Resource.file_name == "payload.png")) is None


def test_resource_requires_exactly_one_source(client, make_user, login):
    user = make_user()
    login(client, user)

    neither = client.post(
        "/resources",
        data=_resource_data(url=""),
        follow_redirects=False,
    )
    assert neither.status_code == 422
    assert "právě jeden" in neither.text.lower()

    both = client.post(
        "/resources",
        data=_resource_data(url="https://example.com/material"),
        files={"file": ("notes.pdf", b"%PDF-1.7\n", "application/pdf")},
        follow_redirects=False,
    )
    assert both.status_code == 422
    assert "právě jeden" in both.text.lower()


def test_resource_links_allow_only_http_and_https(client, db, make_user, login):
    user = make_user()
    login(client, user)

    for bad_url in ("javascript:alert(1)", "data:text/plain,hello"):
        response = client.post(
            "/resources",
            data=_resource_data(url=bad_url),
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert "http" in response.text.lower()

    good = client.post(
        "/resources",
        data=_resource_data(url="https://example.com/material"),
        follow_redirects=False,
    )
    assert good.status_code == 303
    resource = db.scalar(select(Resource).where(Resource.title == "Testovací materiál"))
    assert resource is not None
    assert resource.url == "https://example.com/material"


def test_resource_filters_and_tag_filter(client, db, make_user, login):
    user = make_user()
    login(client, user)
    client.post("/resources", data=_resource_data(title="Matika", subject="Matematika", school_year="2", tags="algebra"), follow_redirects=False)
    client.post("/resources", data=_resource_data(title="Fyzika", subject="Fyzika", school_year="3", tags="mechanika"), follow_redirects=False)

    response = client.get("/resources?subject=Matematika&year=2")
    assert response.status_code == 200
    assert "Matika" in response.text
    assert "Fyzika" not in response.text

    response = client.get("/resources?tag=mechanika")
    assert response.status_code == 200
    assert "Fyzika" in response.text
    assert "Matika" not in response.text
    assert db.scalar(select(Tag).where(Tag.name == "algebra")) is not None


def test_resource_download_increments_counter_and_sets_safe_headers(client, db, make_user, login, tmp_path, monkeypatch):
    user = make_user()
    monkeypatch.setattr("app.core.storage.settings.upload_dir", str(tmp_path), raising=False)
    monkeypatch.setattr("app.routers.resources.settings.upload_dir", str(tmp_path), raising=False)
    relative = save_bytes("resources", b"%PDF-1.7\n", "pdf")
    resource = Resource(
        author_id=user.id,
        title="Ke stažení",
        description="",
        subject="Matematika",
        school_year=1,
        kind="notes",
        file_path=relative,
        file_name="Materiál.pdf",
        file_size=8,
        file_mime="application/pdf",
        status="visible",
        downloads_count=0,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    login(client, user)

    response = client.get(f"/resources/{resource.id}/download")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\n"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"].startswith("attachment; filename*=UTF-8''")
    db.refresh(resource)
    assert resource.downloads_count == 1