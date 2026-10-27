"""Parser de imagen: extrae dimensiones y prepara el contenido para Vision."""

from __future__ import annotations

import io
from typing import Any

from mia.attachments.model import AttachmentContent, AttachmentContentType


def parse_image(content: bytes) -> AttachmentContent:
    """Extrae dimensiones y marca el adjunto para procesamiento con Vision."""
    from PIL import Image  # noqa: PLC0415

    metadata: dict[str, Any] = {}
    try:
        img = Image.open(io.BytesIO(content))
        metadata["width"] = img.width
        metadata["height"] = img.height
        metadata["format"] = (img.format or "").upper()
        metadata["mode"] = img.mode
    except Exception:
        metadata["format"] = "unknown"

    return AttachmentContent(
        content_type=AttachmentContentType.IMAGE,
        metadata=metadata,
        # vision_description se rellenará después por AttachmentIntelligence
    )
