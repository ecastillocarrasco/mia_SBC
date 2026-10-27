"""Compatibilidad: el modelo de informe compartido vive en ``mia.reporting.document``."""

from mia.reporting.document import (
    Block,
    Document,
    annex_block,
    format_number,
    methodology_block,
    narrative_block,
    narrative_statement,
    to_document,
    warnings_block,
)
from mia.reporting.render_docx import to_docx

__all__ = [
    "Block",
    "Document",
    "annex_block",
    "format_number",
    "methodology_block",
    "narrative_block",
    "narrative_statement",
    "to_document",
    "to_docx",
    "warnings_block",
]
