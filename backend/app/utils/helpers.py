"""Shared helpers."""
from __future__ import annotations

import base64
import hashlib
import io
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.config.settings import settings


def generate_session_code(year: int | None = None, sequence: int | None = None) -> str:
    """ER-YYYY-NNNNNN style session code."""
    year = year or datetime.now(UTC).year
    return f"ER-{year}-{sequence:06d}" if sequence is not None else f"ER-{year}-{int(datetime.now(UTC).timestamp() * 1000) % 1000000:06d}"


def next_session_code(db) -> str:
    from app.models import EmergencySession

    year = datetime.now(UTC).year
    prefix = f"ER-{year}-"
    count = (
        db.query(EmergencySession)
        .filter(EmergencySession.session_code.like(f"{prefix}%"))
        .count()
    )
    return generate_session_code(year, count + 1)


def hash_device_id(device_id: str | None) -> str | None:
    if not device_id:
        return None
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:32]


_MAX_SIZE = settings.MAX_UPLOAD_BYTES
_MIME = settings.ALLOWED_IMAGE_MIMES


def validate_and_decode_image(data: str, field: str = "image") -> bytes:
    """Strict validation of base64 image upload: size, magic bytes, format."""
    if len(data) > _MAX_SIZE * 2:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{field} exceeds maximum allowed size",
        )
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid base64 encoding",
        )
    if len(raw) > _MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{field} exceeds maximum allowed size",
        )
    if len(raw) < 16:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image data too small",
        )
    magic = raw[:16]
    detected = None
    if magic.startswith(b"\xff\xd8"):
        detected = "image/jpeg"
    elif magic.startswith(b"\x89PNG"):
        detected = "image/png"
    elif magic.startswith(b"RIFF"):
        detected = "image/webp"
    if detected not in _MIME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported image format (JPEG, PNG, WebP only)",
        )
    # ensure it actually decodes as an image
    from PIL import Image

    try:
        Image.open(io.BytesIO(raw)).load()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image could not be decoded",
        )
    return raw


def is_public_emergency_path(path: str) -> bool:
    return bool(re.match(r"^/api/emergency", path))


def to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
