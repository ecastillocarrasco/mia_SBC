"""Parser de Excel (xlsx/xls): hojas, cabeceras, filas y tipos detectados.

NO convierte a texto plano. Extrae estructura para operaciones deterministas.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from mia.attachments.model import AttachmentContent, AttachmentContentType, DatasetSheet

_MAX_ROWS_PER_SHEET = 5000
_MAX_COLS = 50


def _infer_type(values: list[Any]) -> str:
    sample = [v for v in values if v is not None][:20]
    if not sample:
        return "empty"
    if all(isinstance(v, (int, float)) for v in sample):
        return "numeric"
    if all(isinstance(v, (date, datetime)) for v in sample):
        return "date"
    if all(isinstance(v, bool) for v in sample):
        return "boolean"
    return "text"


def _cell_value(cell: Any) -> Any:
    v = cell.value
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def parse_excel(content: bytes) -> AttachmentContent:
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)

    sheets: list[DatasetSheet] = []
    metadata: dict[str, Any] = {
        "sheet_names": wb.sheetnames,
        "sheet_count": len(wb.sheetnames),
    }

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=False)

        # Primera fila como cabeceras
        try:
            header_row = next(rows_iter)
        except StopIteration:
            sheets.append(DatasetSheet(name=sheet_name, headers=[], rows=[], row_count=0))
            continue

        headers: list[str] = []
        for cell in list(header_row)[:_MAX_COLS]:
            v = cell.value
            headers.append(str(v).strip() if v is not None else f"Col{len(headers) + 1}")

        if not any(h.strip() for h in headers):
            sheets.append(DatasetSheet(name=sheet_name, headers=[], rows=[], row_count=0))
            continue

        data_rows: list[list[Any]] = []
        for row in rows_iter:
            if len(data_rows) >= _MAX_ROWS_PER_SHEET:
                break
            values = [_cell_value(cell) for cell in list(row)[: len(headers)]]
            if any(v is not None for v in values):
                data_rows.append(values)

        # Inferir tipos por columna
        col_values: dict[str, list[Any]] = {h: [] for h in headers}
        for row in data_rows:
            for i, h in enumerate(headers):
                if i < len(row):
                    col_values[h].append(row[i])

        inferred = {h: _infer_type(col_values[h]) for h in headers}

        sheets.append(
            DatasetSheet(
                name=sheet_name,
                headers=headers,
                rows=data_rows,
                inferred_types=inferred,
                row_count=len(data_rows),
            )
        )

    wb.close()
    metadata["total_rows"] = sum(s.row_count for s in sheets)

    return AttachmentContent(
        content_type=AttachmentContentType.DATASET,
        sheets=sheets,
        metadata=metadata,
    )
