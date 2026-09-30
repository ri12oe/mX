"""Image input (design.md §5, §7): decode and check uploads, and serve stored images."""
import base64
import binascii
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from api import db
from api.deps import get_db, require_auth
from providers.base import ImageData

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # after decoding (the Claude API's per-image limit)
DATA_URL_PREFIX = "data:"

router = APIRouter(dependencies=[Depends(require_auth)])


class ImageError(ValueError):
    """An uploaded image is invalid; the message is safe to show the client."""


def decode_images(values: list[str]) -> list[ImageData]:
    if len(values) > MAX_IMAGES:
        raise ImageError(f"At most {MAX_IMAGES} images per message.")
    return [decode_image(value, index) for index, value in enumerate(values, start=1)]


def decode_image(value: str, index: int = 1) -> ImageData:
    """Base64 (optionally a data: URL) → bytes, with the type read from the bytes themselves."""
    if value.startswith(DATA_URL_PREFIX):
        value = value.partition(",")[2]
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ImageError(f"Image {index} is not valid base64.") from None
    if not data:
        raise ImageError(f"Image {index} is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"Image {index} is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    media_type = sniff_media_type(data)
    if media_type is None:
        raise ImageError(f"Image {index} must be JPEG, PNG, GIF, or WebP.")
    return ImageData(media_type=media_type, data=data)


def sniff_media_type(data: bytes) -> str | None:
    """Identify the format from its signature bytes; never trust a client-supplied type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/images/{image_id}")
def get_image(image_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """The stored image bytes, so the UI can show images from past messages."""
    image = db.get_image(conn, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    media_type, data = image
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",  # ids never change
            "X-Content-Type-Options": "nosniff",
        },
    )
