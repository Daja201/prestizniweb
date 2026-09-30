# Covers image normalization and the meme feed's access and interaction rules.
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.models import Meme, MemeLike
from app.services.images import process_image


def _image_bytes(format_name: str = "PNG", size: tuple[int, int] = (320, 240)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (24, 130, 110)).save(output, format_name)
    return output.getvalue()


@pytest.mark.parametrize("format_name", ["PNG", "JPEG", "WEBP"])
def test_process_image_outputs_webp(format_name: str) -> None:
    result = process_image(_image_bytes(format_name))
    normalized = Image.open(BytesIO(result.image_bytes))
    thumbnail = Image.open(BytesIO(result.thumb_bytes))
    assert normalized.format == "WEBP"
    assert thumbnail.format == "WEBP"
    assert (result.width, result.height) == (320, 240)
    assert thumbnail.width == 480
    assert not normalized.getexif()


def test_process_image_rejects_non_image() -> None:
    with pytest.raises(ValueError):
        process_image(b"this is not an image renamed to .jpg")


def test_process_image_strips_exif_and_applies_orientation() -> None:
    source = Image.new("RGB", (320, 240), (24, 130, 110))
    exif = source.getexif()
    exif[274] = 6
    output = BytesIO()
    source.save(output, "JPEG", exif=exif)

    result = process_image(output.getvalue())
    normalized = Image.open(BytesIO(result.image_bytes))
    assert (result.width, result.height) == (240, 320)
    assert not normalized.getexif()


def test_process_image_enforces_input_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_image_mb", 1)
    with pytest.raises(ValueError, match="nejvýše"):
        process_image(b"x" * (1024 * 1024 + 1))


def _add_meme(db, author_id: int, caption: str, status: str = "visible") -> Meme:
    meme = Meme(
        author_id=author_id,
        caption=caption,
        image_path="memes/test/main.webp",
        thumb_path="memes/test/thumb.webp",
        width=320,
        height=240,
        status=status,
    )
    db.add(meme)
    db.commit()
    db.refresh(meme)
    return meme


def test_like_toggle_updates_counter_only_on_real_change(client, db, make_user, login) -> None:
    user = make_user()
    meme = _add_meme(db, user.id, "like test")
    login(client, user)

    first = client.post(f"/memes/{meme.id}/like")
    assert first.status_code == 200
    db.refresh(meme)
    assert meme.likes_count == 1
    assert db.scalar(select(MemeLike).where(MemeLike.meme_id == meme.id, MemeLike.user_id == user.id))

    second = client.post(f"/memes/{meme.id}/like")
    assert second.status_code == 200
    db.refresh(meme)
    assert meme.likes_count == 0
    assert db.scalar(select(MemeLike).where(MemeLike.meme_id == meme.id, MemeLike.user_id == user.id)) is None


def test_feed_cursor_and_hidden_deleted_visibility(client, db, make_user, login) -> None:
    author = make_user()
    student = make_user()
    memes = [_add_meme(db, author.id, f"caption-{index}") for index in range(3)]
    hidden = _add_meme(db, author.id, "hidden-caption", "hidden")
    deleted = _add_meme(db, author.id, "deleted-caption", "deleted")
    login(client, student)

    first_page = client.get("/memes?limit=2")
    assert first_page.status_code == 200
    assert "caption-2" in first_page.text and "caption-1" in first_page.text
    assert "hx-get=\"/memes?before=" in first_page.text
    next_page = client.get(f"/memes?before={memes[1].id}&limit=2")
    assert "caption-0" in next_page.text
    assert "hidden-caption" not in client.get(f"/memes/{hidden.id}").text
    assert client.get(f"/memes/{deleted.id}").status_code == 404


def test_feed_sort_recent_and_popular_and_no_class_filter(client, db, make_user, login) -> None:
    author = make_user()
    viewer = make_user()
    popular_old = _add_meme(db, author.id, "popular older meme")
    recent_new = _add_meme(db, author.id, "recent newer meme")
    popular_old.likes_count = 12
    recent_new.likes_count = 1
    db.commit()
    login(client, viewer)

    recent_page = client.get("/memes?sort=new")
    assert recent_page.text.index("recent newer meme") < recent_page.text.index("popular older meme")
    assert 'name="class"' not in recent_page.text

    popular_page = client.get("/memes?sort=popular")
    assert popular_page.text.index("popular older meme") < popular_page.text.index("recent newer meme")


def test_hidden_meme_is_available_to_admin(client, db, make_user, login) -> None:
    author = make_user()
    moderator = make_user(role="admin")
    hidden = _add_meme(db, author.id, "moderator-only", "hidden")
    login(client, moderator)
    response = client.get(f"/memes/{hidden.id}")
    assert response.status_code == 200
    assert "Skryto" in response.text


def test_delete_is_author_only(client, db, make_user, login) -> None:
    author = make_user()
    other = make_user()
    meme = _add_meme(db, author.id, "owner only")
    login(client, other)
    assert client.post(f"/memes/{meme.id}/delete").status_code == 303
    db.refresh(meme)
    assert meme.status == "visible"