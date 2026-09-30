# Covers shared storage safety and Czech date/time template helpers.
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import storage
from app.core.config import settings
from app.core.templates import cs_date, media_url, timeago


def test_storage_round_trip_and_traversal_guard(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    relative_path = storage.save_bytes("memes", b"image-data", "webp")
    assert storage.abs_path(relative_path).read_bytes() == b"image-data"
    assert len(relative_path.split("/")[1]) == 2
    with pytest.raises(ValueError):
        storage.abs_path("../outside")


def test_storage_extension_validation() -> None:
    with pytest.raises(ValueError):
        storage.save_bytes("memes", b"data", "../jpg")


def test_czech_date_and_timeago_plural_forms() -> None:
    assert cs_date(date(2026, 9, 30)) == "30. září 2026"
    now = datetime.now(timezone.utc)
    assert timeago(now - timedelta(minutes=1)) == "před 1 minutou"
    assert timeago(now - timedelta(minutes=2)) == "před 2 minutami"
    assert timeago(now - timedelta(minutes=5)) == "před 5 minutami"
    assert media_url("memes/ab/file.webp") == "/media/memes/ab/file.webp"