# Validates and normalizes uploads into metadata-free WebP images and thumbnails.
from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


@dataclass(frozen=True)
class ProcessedImage:
    image_bytes: bytes
    thumb_bytes: bytes
    width: int
    height: int


def process_image(data: bytes) -> ProcessedImage:
    if not data:
        raise ValueError("Obrázek je prázdný.")
    if len(data) > settings.max_image_mb * 1024 * 1024:
        raise ValueError(f"Obrázek může mít nejvýše {settings.max_image_mb} MB.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in _ALLOWED_FORMATS:
                    raise ValueError("Povolené jsou pouze obrázky JPEG, PNG, WebP nebo GIF.")
                probe.verify()
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in _ALLOWED_FORMATS:
                    raise ValueError("Povolené jsou pouze obrázky JPEG, PNG, WebP nebo GIF.")
                source.seek(0)
                image = ImageOps.exif_transpose(source.copy())
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
                image.info.clear()
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                width, height = image.size

                thumb_height = max(1, round(height * 480 / width))
                thumbnail = image.resize((480, thumb_height), Image.Resampling.LANCZOS)
                thumbnail.info.clear()

                main_buffer = io.BytesIO()
                thumb_buffer = io.BytesIO()
                image.save(main_buffer, format="WEBP", quality=80, method=4)
                thumbnail.save(thumb_buffer, format="WEBP", quality=75, method=4)
                return ProcessedImage(main_buffer.getvalue(), thumb_buffer.getvalue(), width, height)
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Soubor není platný nebo bezpečný obrázek.") from exc