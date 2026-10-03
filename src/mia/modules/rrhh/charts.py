"""Cuándo un resultado merece un gráfico y cuál: un recuento por categorías (tabla de dos columnas: categoría y
cantidad) o una serie temporal. Lo comparten la pantalla (2D) y los informes (PDF, Excel, PowerPoint)."""

from __future__ import annotations

import re
from typing import Any

MAX_CHART_ROWS = 24
NOT_CHARTABLE_HEADERS = {"indicador", "concepto", "metrica", "métrica", "campo", "dato", "#"}
_TIME_LABEL = re.compile(
    r"^(\d{4}-\d{2}(-\d{2})?|\d{1,2}/\d{1,2}(/\d{2,4})?|(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\w*)$",
    re.IGNORECASE,
)
_ES_NUMBER = re.compile(r"-?[\d.]+,\d+|-?\d+")


def to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not _ES_NUMBER.fullmatch(text):
        return None
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def chart_spec(title: str | None, columns: list[str], rows: list[list[Any]]) -> dict[str, Any] | None:
    """{type: bar|donut|line, title, labels, series:[{name, values}]} o None si no procede un gráfico."""
    if len(columns) != 2 or not (2 <= len(rows) <= MAX_CHART_ROWS):
        return None
    if str(columns[0]).lower() in NOT_CHARTABLE_HEADERS or str(title or "").startswith("Departamento ·"):
        return None
    labels = [str(r[0]) if len(r) > 0 and r[0] not in (None, "") else "Sin dato" for r in rows]
    values = [to_number(r[1]) if len(r) > 1 else None for r in rows]
    if any(v is None for v in values) or len(set(labels)) != len(labels) or sum(v or 0 for v in values) <= 0:
        return None
    if any(to_number(label) is not None and len(label) > 3 for label in labels):
        return None
    time_like = all(_TIME_LABEL.match(label) for label in labels)
    kind = "line" if time_like else ("donut" if len(rows) <= 6 else "bar")
    return {
        "type": kind,
        "title": title,
        "labels": labels,
        "series": [{"name": str(columns[1]), "values": [float(v or 0) for v in values]}],
    }
