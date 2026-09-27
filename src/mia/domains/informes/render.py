"""Generación de informes a partir de una tabla de resultados."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

HEADER_FILL = "1F4E78"


def to_xlsx(title: str, columns: list[str], rows: list[list[Any]], generated: datetime) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Sunset Beach Club · generado por mIA el {generated:%d/%m/%Y %H:%M}"
    ws["A2"].font = Font(italic=True, size=9, color="666666")
    header_row = 4
    for i, name in enumerate(columns, 1):
        cell = ws.cell(row=header_row, column=i, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r, row in enumerate(rows, header_row + 1):
        for c, value in enumerate(row, 1):
            ws.cell(row=r, column=c, value=value)
    for i, name in enumerate(columns, 1):
        width = max([len(str(name))] + [len(str(row[i - 1] or "")) for row in rows[:500]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 8), 60)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if rows:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(columns))}{header_row + len(rows)}"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def to_pdf(title: str, columns: list[str], rows: list[list[Any]], generated: datetime) -> bytes:
    from reportlab.lib import colors  # noqa: PLC0415
    from reportlab.lib.pagesizes import A4, landscape  # noqa: PLC0415
    from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
    from reportlab.lib.units import cm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: PLC0415

    buffer = io.BytesIO()
    page = landscape(A4) if len(columns) > 4 else A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=title,
        author="mIA",
    )
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=7.5, leading=9)
    head = cell.clone("head", textColor=colors.white, fontName="Helvetica-Bold")

    def para(value: Any, style: Any) -> Paragraph:
        text = "" if value is None else str(value)
        return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)

    data = [[para(c, head) for c in columns]] + [[para(v, cell) for v in row] for row in rows]
    width = page[0] - 3 * cm
    grid = Table(data, colWidths=[width / max(1, len(columns))] * len(columns), repeatRows=1)
    grid.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{HEADER_FILL}")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8D3DE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story = [
        Paragraph(title.replace("&", "&amp;"), styles["Title"]),
        Paragraph(
            f"Sunset Beach Club · generado por mIA el {generated:%d/%m/%Y %H:%M} · {len(rows)} filas",
            styles["Italic"],
        ),
        Spacer(1, 0.4 * cm),
        grid,
    ]
    doc.build(story)
    return buffer.getvalue()
