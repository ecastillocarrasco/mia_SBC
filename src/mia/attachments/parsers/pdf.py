"""Parser de PDF: extracción de texto, tablas y metadatos.

Prefiere extracción directa de texto (nativo). Si el PDF parece escaneado
(sin texto extraíble), indica que se necesita Vision.
"""

from __future__ import annotations

import io
from typing import Any

from mia.attachments.model import AttachmentContent, AttachmentContentType, TableBlock, TextBlock


_MIN_TEXT_PER_PAGE = 30
"""Mínimo de caracteres por página para considerar que hay texto nativo."""


def parse_pdf(content: bytes) -> AttachmentContent:
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(io.BytesIO(content))

    # Metadatos
    meta_raw: Any = reader.metadata or {}
    metadata: dict[str, Any] = {
        "page_count": len(reader.pages),
        "title": str(meta_raw.get("/Title") or ""),
        "author": str(meta_raw.get("/Author") or ""),
        "creator": str(meta_raw.get("/Creator") or ""),
    }

    text_blocks: list[TextBlock] = []
    tables: list[TableBlock] = []
    scanned_pages = 0

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()

        if len(text) < _MIN_TEXT_PER_PAGE:
            scanned_pages += 1
            continue

        # Añadir como bloque de texto con referencia de página
        text_blocks.append(TextBlock(text=text, source_ref=f"page={page_num}"))

    parse_error = ""
    if scanned_pages and not text_blocks:
        parse_error = (
            f"El PDF contiene {scanned_pages} página(s) escaneada(s). "
            "Usa Vision para interpretar las imágenes."
        )
    elif scanned_pages:
        parse_error = f"{scanned_pages} página(s) escaneada(s) sin texto extraíble."

    metadata["scanned_pages"] = scanned_pages
    metadata["text_pages"] = len(text_blocks)

    return AttachmentContent(
        content_type=AttachmentContentType.DOCUMENT,
        text_blocks=text_blocks,
        tables=tables,
        metadata=metadata,
        parse_error=parse_error,
    )


def needs_vision(content: AttachmentContent) -> bool:
    """Devuelve True si el PDF no tiene texto nativo y debería procesarse con Vision."""
    return not content.text_blocks and bool(content.parse_error)
