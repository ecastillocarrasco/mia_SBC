"""Lectura en el momento de documentos de bibliotecas (nóminas, documentos firmados).

El contenido nunca se guarda: se descarga, se extrae el texto y se descarta.
"""

from __future__ import annotations

import io
from typing import Any

from mia.conversation import ToolResult, ToolStatus
from mia.domains.curriculums.indexer import clean_text

MAX_BYTES = 15 * 1024 * 1024


def pdf_lines(content: bytes) -> str:
    """Texto de un PDF conservando los saltos de línea (los lectores de importes los necesitan)."""
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages).replace("\x00", " ")


def document_text(content: bytes) -> str | None:
    if content[:4] == b"%PDF":
        return clean_text(pdf_lines(content))
    if content[:2] == b"PK":
        import docx  # noqa: PLC0415

        document = docx.Document(io.BytesIO(content))
        return clean_text("\n".join(p.text for p in document.paragraphs))
    return None


def content_unavailable(deps: Any) -> ToolResult | None:
    if deps.sharepoint is None:
        return ToolResult(
            ToolStatus.SOURCE_UNAVAILABLE, "SharePoint no está configurado para leer documentos"
        )
    if deps.settings is not None and not deps.settings.data.content_enabled:
        return ToolResult(
            ToolStatus.PERMISSION_DENIED, "La lectura de contenido está desactivada en la configuración"
        )
    return None
