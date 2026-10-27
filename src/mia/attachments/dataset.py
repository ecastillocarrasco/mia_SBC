"""Operaciones estructuradas y deterministas sobre datasets de adjuntos (Excel/CSV).

No delega cálculos simples al LLM. Devuelve resultados reproducibles.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from mia.attachments.model import AttachmentContent, DatasetSheet


def _find_sheet(content: AttachmentContent, sheet_name: str | None = None) -> DatasetSheet | None:
    if not content.sheets:
        return None
    if not sheet_name:
        return content.sheets[0]
    name_lower = sheet_name.strip().lower()
    for s in content.sheets:
        if s.name.lower() == name_lower:
            return s
    # Búsqueda parcial
    for s in content.sheets:
        if name_lower in s.name.lower():
            return s
    return None


def _col_index(sheet: DatasetSheet, col_name: str) -> int | None:
    col_lower = col_name.strip().lower()
    for i, h in enumerate(sheet.headers):
        if h.lower() == col_lower or col_lower in h.lower():
            return i
    return None


def dataset_info(content: AttachmentContent) -> dict[str, Any]:
    """Devuelve descripción estructural del dataset."""
    sheets_info = []
    for s in content.sheets:
        sheets_info.append(
            {
                "name": s.name,
                "headers": s.headers,
                "row_count": s.row_count,
                "col_count": len(s.headers),
                "inferred_types": s.inferred_types,
                "null_counts": _null_counts(s),
            }
        )
    return {
        "sheet_count": len(content.sheets),
        "sheets": sheets_info,
        "total_rows": content.total_rows,
    }


def _null_counts(sheet: DatasetSheet) -> dict[str, int]:
    counts: dict[str, int] = {h: 0 for h in sheet.headers}
    for row in sheet.rows:
        for i, h in enumerate(sheet.headers):
            if i < len(row) and (row[i] is None or str(row[i]).strip() in ("", "None", "N/A", "-", "—")):
                counts[h] += 1
    return counts


def dataset_query(
    content: AttachmentContent,
    *,
    sheet_name: str | None = None,
    filter_col: str | None = None,
    filter_value: str | None = None,
    group_by: str | None = None,
    aggregate: str | None = None,
    agg_col: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Filtra, agrupa o agrega filas de un dataset."""
    sheet = _find_sheet(content, sheet_name)
    if sheet is None:
        return {"error": "No se encontraron datos estructurados."}

    rows = sheet.rows
    headers = sheet.headers

    # Filtrar
    if filter_col and filter_value is not None:
        col_idx = _col_index(sheet, filter_col)
        if col_idx is None:
            return {"error": f"Columna «{filter_col}» no encontrada."}
        pattern = re.compile(re.escape(filter_value), re.IGNORECASE)
        rows = [r for r in rows if col_idx < len(r) and r[col_idx] is not None and pattern.search(str(r[col_idx]))]

    # Agrupar y agregar
    if group_by:
        gcol = _col_index(sheet, group_by)
        if gcol is None:
            return {"error": f"Columna «{group_by}» no encontrada."}

        groups: defaultdict[str, list[list[Any]]] = defaultdict(list)
        for row in rows:
            key = str(row[gcol]) if gcol < len(row) and row[gcol] is not None else "—"
            groups[key].append(row)

        agg_fn = (aggregate or "count").lower()
        result_rows = []
        for key, group_rows in sorted(groups.items()):
            if agg_fn == "count":
                result_rows.append([key, len(group_rows)])
            elif agg_fn in ("sum", "avg", "mean") and agg_col:
                acol = _col_index(sheet, agg_col)
                if acol is None:
                    return {"error": f"Columna «{agg_col}» no encontrada."}
                numeric = [row[acol] for row in group_rows if acol < len(row) and isinstance(row[acol], (int, float))]
                if agg_fn == "sum":
                    val: float | str = sum(numeric) if numeric else 0
                else:
                    val = round(sum(numeric) / len(numeric), 2) if numeric else 0
                result_rows.append([key, val])
            else:
                result_rows.append([key, len(group_rows)])

        agg_label = f"{agg_fn}({agg_col})" if agg_col else "count"
        return {
            "sheet": sheet.name,
            "group_by": group_by,
            "aggregation": agg_label,
            "rows": result_rows[:limit],
            "total_groups": len(result_rows),
        }

    # Sin agrupación: devolver filas
    result_headers = headers
    result_data = [{h: (row[i] if i < len(row) else None) for i, h in enumerate(headers)} for row in rows[:limit]]

    return {
        "sheet": sheet.name,
        "headers": result_headers,
        "rows": result_data,
        "total_matching": len(rows),
        "shown": min(limit, len(rows)),
    }


def extract_column(
    content: AttachmentContent,
    col_name: str,
    sheet_name: str | None = None,
) -> list[Any]:
    """Extrae todos los valores únicos no nulos de una columna."""
    sheet = _find_sheet(content, sheet_name)
    if sheet is None:
        return []
    col_idx = _col_index(sheet, col_name)
    if col_idx is None:
        return []
    seen: set[str] = set()
    result: list[Any] = []
    for row in sheet.rows:
        if col_idx < len(row) and row[col_idx] is not None:
            v = row[col_idx]
            k = str(v).strip().lower()
            if k and k not in seen:
                seen.add(k)
                result.append(v)
    return result


def find_people_column(sheet: DatasetSheet) -> int | None:
    """Intenta encontrar la columna más probable de nombres de persona."""
    name_patterns = re.compile(r"nombre|empleado|persona|trabajador|name|employee", re.IGNORECASE)
    for i, h in enumerate(sheet.headers):
        if name_patterns.search(h):
            return i
    # Fallback: primera columna de texto con valores parecidos a nombres
    if sheet.headers:
        return 0
    return None
