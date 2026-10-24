"""Renderizado DOCX del modelo de documento común de mIA."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document as WordDocument
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.shared import Inches, Pt, RGBColor

from mia.assets import resolve_logo
from mia.reporting.document import Document


def _cell_text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, dict | list):
        return str(value)
    return str(value)


def to_docx(doc: Document, generated: datetime, logo: Path | None = None) -> bytes:  # noqa: PLR0915
    """Genera un Word editable con títulos, metadatos y tablas semánticas de cada bloque."""
    from mia.reporting.render import _rows  # noqa: PLC0415

    word = WordDocument()
    section = word.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    styles = word.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(9)
    styles["Normal"].font.color.rgb = RGBColor(45, 52, 71)
    styles["Title"].font.name = "Aptos Display"
    styles["Title"].font.size = Pt(25)
    styles["Title"].font.bold = True
    styles["Title"].font.color.rgb = RGBColor(27, 37, 89)

    header = section.header.paragraphs[0]
    header.text = "SUNSET BEACH CLUB  ·  mIA"
    header.style = "Subtitle"
    header.runs[0].font.color.rgb = RGBColor(27, 37, 89)
    header.runs[0].font.bold = True
    header.runs[0].font.size = Pt(9)
    logo_path = resolve_logo(logo)
    if logo_path is not None and logo_path.is_file():
        header.add_run("\t")
        header.add_run().add_picture(str(logo_path), width=Inches(0.85))

    word.add_heading(doc.title, 0)
    if doc.subtitle:
        word.add_paragraph(doc.subtitle, style="Subtitle")
    if doc.badges:
        word.add_paragraph("  ·  ".join(str(item) for item in doc.badges))
    word.add_paragraph(f"Generado el {generated:%d/%m/%Y %H:%M}", style="Caption")

    for block in doc.blocks:
        word.add_heading(block.title, level=1)
        columns, rows = _rows(block)
        if not columns:
            continue
        table = word.add_table(rows=1, cols=len(columns))
        table.style = "Light Shading Accent 1"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for cell, value in zip(table.rows[0].cells, columns, strict=True):
            cell.text = str(value)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for run in cell.paragraphs[0].runs:
                run.font.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
        for row in rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row, strict=False):
                cell.text = _cell_text(value)
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if block.kind == "annex" and block.data.get("truncated"):
            word.add_paragraph(
                f"Mostrando {len(block.data.get('rows', []))} de {block.data.get('total_rows')} filas.",
                style="Caption",
            )

    footer = section.footer.paragraphs[0]
    footer.text = "Documento generado por mIA · Sunset Beach Club"
    footer.alignment = 1
    for run in footer.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(107, 111, 128)

    output = io.BytesIO()
    word.save(output)
    return output.getvalue()
