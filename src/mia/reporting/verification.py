"""Comprueba la estructura y el contenido textual del archivo antes de publicarlo.

No certifica causalidad ni la geometría visual de los gráficos. Las cifras siguen
procediendo del Document calculado y la narrativa conserva sus guardas previas.
"""

from __future__ import annotations

import io
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

from mia.reporting.cells import pptx_row_fragments, typed_value
from mia.reporting.document import Block, Document


class ReportVerificationError(ValueError):
    """El documento no puede publicarse con las garantías estructurales exigidas."""


def verify_document(document: Document) -> None:
    if not document.title.strip() or not document.blocks:
        raise ReportVerificationError("El informe necesita título y contenido.")
    for block in document.blocks:
        if block.kind in {"table", "annex"}:
            columns = block.data.get("columns", [])
            if not columns or any(len(row) != len(columns) for row in block.data.get("rows", [])):
                raise ReportVerificationError("Una tabla del informe tiene una estructura incoherente.")
        elif block.kind == "chart":
            labels = block.data.get("labels", [])
            series = block.data.get("series", [])
            if not labels or not series or any(len(s.get("values", [])) != len(labels) for s in series):
                raise ReportVerificationError("Un gráfico tiene categorías y valores incompatibles.")


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _extract_content(fmt: str, content: bytes) -> tuple[str, list[list[Any]]]:
    if fmt == "html":
        parser = _HTMLText()
        parser.feed(content.decode("utf-8"))
        return " ".join(parser.parts), []
    if fmt == "pdf":
        from pypdf import PdfReader  # noqa: PLC0415 — cargar solo el lector del formato solicitado

        return " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages), []
    if fmt == "xlsx":
        from openpyxl import load_workbook  # noqa: PLC0415 — evitar cargar lectores en cada arranque

        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        try:
            rows = [list(row) for sheet in book for row in sheet.values]
            return " ".join(str(value) for row in rows for value in row if value is not None), rows
        finally:
            book.close()
    if fmt == "docx":
        from docx import Document as WordDocument  # noqa: PLC0415 — lector opcional según formato

        word = WordDocument(io.BytesIO(content))
        rows = [[cell.text for cell in row.cells] for table in word.tables for row in table.rows]
        return " ".join([p.text for p in word.paragraphs] + [str(cell) for row in rows for cell in row]), rows
    if fmt == "pptx":
        from pptx import Presentation  # noqa: PLC0415 — lector opcional según formato

        deck = Presentation(io.BytesIO(content))
        parts: list[str] = []
        rows = []
        for slide in deck.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    parts.append(shape.text)
                if shape.has_table:
                    rows += [[cell.text for cell in row.cells] for row in shape.table.rows]
        return " ".join(parts + [str(cell) for row in rows for cell in row]), rows
    raise ReportVerificationError("No hay verificador para este formato.")


def _key(value: Any) -> str:
    # Los renderizadores pueden dividir palabras por salto de línea o eliminar
    # controles invisibles; se conserva la secuencia de letras y dígitos.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    normalized = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"[^\w-]|_", "", normalized.replace("−", "-")).casefold()


def verify_artifact(fmt: str, content: bytes, document: Document) -> None:
    """Lee los bytes reales; bloquea archivos corruptos o con celdas omitidas.

    En Excel, Word y PowerPoint comprueba también la asociación de celdas por
    fila. En PDF/HTML comprueba presencia textual; no certifica disposición visual
    ni equivalencia semántica con toda petición libre. No publica valores en errores.
    """
    verify_document(document)
    try:
        raw_text, rows = _extract_content(fmt, content)
        text = _key(raw_text)
    except Exception as exc:
        raise ReportVerificationError("No se puede leer el archivo generado para verificarlo.") from exc
    if not text:
        raise ReportVerificationError("El archivo generado no contiene texto verificable.")
    actual_cells = {_numeric_key(value) for row in rows for value in row if value not in (None, "")}
    for block in document.blocks:
        _verify_kpis(block, fmt, text, actual_cells)
        if block.kind == "narrative":
            for statement in block.data.get("statements", []):
                expected = _key(statement.get("text", ""))
                if expected and expected not in text:
                    raise ReportVerificationError("El archivo generado omite una conclusión del informe.")
        if block.kind not in {"table", "annex"}:
            continue
        _verify_table(block, fmt, text, rows)


def _verify_kpis(block: Block, fmt: str, text: str, actual_cells: set[str]) -> None:
    kpis = block.data if block.kind == "kpis" else block.data.get("kpis", {}) if isinstance(block.data, dict) else {}
    if not isinstance(kpis, dict):
        return
    for value in kpis.values():
        if value is None or isinstance(value, (dict, list, bool)):
            continue
        expected = _numeric_key(typed_value(value)[0]) if fmt == "xlsx" else _key(value)
        if expected and (expected not in actual_cells if fmt == "xlsx" else expected not in text):
            raise ReportVerificationError("El archivo generado no conserva un indicador del informe.")


def _numeric_key(value: Any) -> str:
    # XLSX serializes numbers with sixteen significant digits. Normalize that
    # representation on both sides, including binary artifacts from percentages.
    return _key(format(value, ".16g") if isinstance(value, float) else value)


def _row_key(row: list[Any], fmt: str) -> tuple[str, ...]:
    cells = [
        "" if value in (None, "") else _numeric_key(typed_value(value)[0]) if fmt == "xlsx" else _key(str(value))
        for value in row
    ]
    # XLSX readers include styled but empty trailing cells. Interior gaps retain
    # their positions so a value moved to a different column is still rejected.
    while cells and not cells[-1]:
        cells.pop()
    return tuple(cells)


def _verify_table(block: Block, fmt: str, text: str, actual_rows: list[list[Any]]) -> None:
    normalized = [_row_key(row, fmt) for row in actual_rows]
    header = _row_key(block.data.get("columns", []), fmt)
    data_rows = [row for row in normalized if row != header]
    for row in block.data.get("rows", []):
        if fmt in {"xlsx", "docx", "pptx"}:
            fragments = pptx_row_fragments(row, len(block.data["columns"])) if fmt == "pptx" else [row]
            expected = [_row_key(fragment, fmt) for fragment in fragments]
            if any(data_rows[i : i + len(expected)] == expected for i in range(len(data_rows) - len(expected) + 1)):
                continue
            raise ReportVerificationError("El archivo no conserva la asociación entre las celdas de una fila.")
        for value in row:
            if value is None or isinstance(value, (dict, list, bool)):
                continue
            expected_cell = _key(value)
            if expected_cell and expected_cell not in text:
                raise ReportVerificationError("El archivo generado omite contenido de una tabla del informe.")
