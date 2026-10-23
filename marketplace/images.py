"""Image handling for slow connections and seller privacy.

* ``normalise_upload`` re-encodes every listing photo: fixes phone rotation, caps the size at
  1600px and saves a JPEG. Re-encoding drops EXIF metadata, including GPS location.
* ``thumbnail_url`` serves small JPEG variants for listing cards, generated on first use.
"""
import io
import logging
import os

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)
MAX_DIMENSION = 1600
UPLOAD_QUALITY = 82
THUMB_QUALITY = 75


def _to_rgb(image):
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background
    return image.convert("RGB") if image.mode != "RGB" else image


MAX_SOURCE_PIXELS = 40_000_000  # ~40 MP: more than any phone camera; blocks "decompression bomb" files.


def normalise_upload(uploaded):
    """Return a metadata-free, size-capped JPEG version of an uploaded image file."""
    uploaded.seek(0)
    with Image.open(uploaded) as source:
        if source.width * source.height > MAX_SOURCE_PIXELS:
            raise ValueError("Image dimensions are too large.")
        image = ImageOps.exif_transpose(source)
        image = _to_rgb(image)
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=UPLOAD_QUALITY, optimize=True, progressive=True)
    stem = os.path.splitext(os.path.basename(uploaded.name or "photo"))[0][:60] or "photo"
    return ContentFile(buffer.getvalue(), name=f"{stem}.jpg")


def thumbnail_url(image_field, width):
    """URL of a ``width``-px-wide JPEG version of ``image_field``; falls back to the original."""
    if not image_field:
        return ""
    name = image_field.name
    thumb_name = f"thumbs/{width}/{os.path.splitext(name)[0]}.jpg"
    cache_key = f"thumb:{thumb_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    try:
        if not default_storage.exists(thumb_name):
            with default_storage.open(name, "rb") as handle, Image.open(handle) as source:
                image = _to_rgb(ImageOps.exif_transpose(source))
                if image.width > width:
                    image = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=THUMB_QUALITY, optimize=True, progressive=True)
            default_storage.save(thumb_name, ContentFile(buffer.getvalue()))
        url = default_storage.url(thumb_name)
        cache.set(cache_key, url, 60 * 60 * 24)
        return url
    except Exception:  # A missing or unreadable original must never break a page.
        logger.warning("Could not create %spx thumbnail for %s", width, name, exc_info=True)
        try:
            fallback = image_field.url
        except ValueError:
            fallback = ""
        cache.set(cache_key, fallback, 60 * 10)  # Try again in 10 minutes, not on every request.
        return fallback
