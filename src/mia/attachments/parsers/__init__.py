"""Parsers de documentos para adjuntos."""

from __future__ import annotations

from mia.attachments.parsers.csv_file import parse_csv
from mia.attachments.parsers.docx import parse_docx
from mia.attachments.parsers.excel import parse_excel
from mia.attachments.parsers.image import parse_image
from mia.attachments.parsers.pdf import parse_pdf

__all__ = ["parse_csv", "parse_docx", "parse_excel", "parse_image", "parse_pdf"]
