"""Selección automática y construcción de gráficos.

Cuándo un resultado merece un gráfico y cuál tipo usar. Lo comparten la
pantalla (2D), los informes (PDF, Excel, PowerPoint) y las nuevas tools
analíticas universales.

Tipos soportados:
  bar          — barras verticales (categorías, ranking)
  horizontal_bar — barras horizontales (rankings largos)
  grouped_bar  — barras agrupadas (comparación de N grupos en M métricas)
  stacked_bar  — barras apiladas (composición por grupos)
  donut        — anillo (composición de pocos elementos, ≤8)
  line         — línea (serie temporal, tendencia)
  area         — área (acumulados, tendencia)
  scatter      — dispersión (correlación, distribución)
  histogram    — histograma (distribución de frecuencias)
  comparison   — comparación lado a lado (2 series en el mismo eje)
"""

from __future__ import annotations

import re
from typing import Any, Literal

MAX_CHART_ROWS = 24
NOT_CHARTABLE_HEADERS = {"indicador", "concepto", "metrica", "métrica", "campo", "dato", "#"}
_TIME_LABEL = re.compile(
    r"^(\d{4}-\d{2}(-\d{2})?|\d{1,2}/\d{1,2}(/\d{2,4})?|(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\w*"
    r"|(Q[1-4]\s*\d{4}))$",
    re.IGNORECASE,
)
_ES_NUMBER = re.compile(r"-?[\d.]+,\d+|-?\d+")

ChartType = Literal[
    "bar", "horizontal_bar", "grouped_bar", "stacked_bar",
    "donut", "line", "area", "scatter", "histogram", "comparison",
]


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


def _is_time_like(labels: list[str]) -> bool:
    return bool(labels) and all(_TIME_LABEL.match(str(lbl)) for lbl in labels)


# ─────────────────────────────────────────────────────────────────────────────
# API pública principal (backward compatible)
# ─────────────────────────────────────────────────────────────────────────────
def chart_spec(title: str | None, columns: list[str], rows: list[list[Any]]) -> dict[str, Any] | None:
    """{type, title, labels, series:[{name, values}]} o None si no procede un gráfico.

    Versión extendida respecto al original: también maneja tablas con 3+ columnas
    numéricas (genera grouped_bar) y series temporales con ≥2 columnas (line multi-series).
    """
    if len(rows) < 2 or len(rows) > MAX_CHART_ROWS:
        return None
    if not columns:
        return None
    col0 = str(columns[0]).lower()
    if col0 in NOT_CHARTABLE_HEADERS or str(title or "").startswith("Departamento ·"):
        return None

    # ── Tabla de 2 columnas (caso original)
    if len(columns) == 2:
        labels = [str(r[0]) if len(r) > 0 and r[0] not in (None, "") else "Sin dato" for r in rows]
        values = [to_number(r[1]) if len(r) > 1 else None for r in rows]
        if any(v is None for v in values):
            return None
        if len(set(labels)) != len(labels):
            return None
        if sum(v or 0 for v in values) <= 0:
            return None
        if any(to_number(label) is not None and len(str(label)) > 3 for label in labels):
            return None
        time_like = _is_time_like(labels)
        kind: ChartType = "line" if time_like else ("donut" if len(rows) <= 6 else "bar")
        return {
            "type": kind,
            "title": title,
            "labels": labels,
            "series": [{"name": str(columns[1]), "values": [float(v or 0) for v in values]}],
        }

    # ── Tabla con etiqueta + N columnas numéricas → grouped_bar o line multi-series
    if len(columns) >= 3:
        return chart_spec_multi(title, columns, rows)

    return None


def chart_spec_multi(
    title: str | None,
    columns: list[str],
    rows: list[list[Any]],
) -> dict[str, Any] | None:
    """Gráfico para tablas con 1 columna categórica + N columnas numéricas (N ≥ 2)."""
    if len(rows) < 2 or len(rows) > MAX_CHART_ROWS:
        return None
    if len(columns) < 3:
        return None

    labels = [str(r[0]) if r and r[0] not in (None, "") else "Sin dato" for r in rows]
    series_specs: list[dict[str, Any]] = []
    for col_idx in range(1, len(columns)):
        values = [to_number(r[col_idx]) if len(r) > col_idx else None for r in rows]
        if any(v is None for v in values):
            continue
        series_specs.append({"name": str(columns[col_idx]), "values": [float(v or 0) for v in values]})

    if not series_specs:
        return None

    time_like = _is_time_like(labels)
    kind: ChartType
    if len(series_specs) == 1:
        kind = "line" if time_like else ("donut" if len(rows) <= 6 else "bar")
    elif time_like:
        kind = "line"  # multi-series line para comparativas temporales
    else:
        kind = "grouped_bar"

    return {
        "type": kind,
        "title": title,
        "labels": labels,
        "series": series_specs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Constructores de gráficos específicos (usados por las nuevas tools)
# ─────────────────────────────────────────────────────────────────────────────
def time_series_chart(
    title: str,
    labels: list[str],
    series: list[dict[str, Any]],
    *,
    chart_type: Literal["line", "area"] = "line",
) -> dict[str, Any]:
    """Gráfico de serie temporal con una o varias series."""
    return {"type": chart_type, "title": title, "labels": labels, "series": series}


def bar_chart(
    title: str,
    labels: list[str],
    values: list[float],
    *,
    series_name: str = "Valor",
    horizontal: bool = False,
    chart_type: ChartType | None = None,
) -> dict[str, Any]:
    """Gráfico de barras simple."""
    kind = chart_type or ("horizontal_bar" if (horizontal or len(labels) > 12) else "bar")
    return {"type": kind, "title": title, "labels": labels, "series": [{"name": series_name, "values": values}]}


def grouped_bar_chart(
    title: str,
    labels: list[str],
    series: list[dict[str, Any]],
) -> dict[str, Any]:
    """Barras agrupadas: múltiples series sobre las mismas etiquetas."""
    return {"type": "grouped_bar", "title": title, "labels": labels, "series": series}


def donut_chart(
    title: str,
    labels: list[str],
    values: list[float],
    *,
    series_name: str = "Valor",
) -> dict[str, Any]:
    return {"type": "donut", "title": title, "labels": labels, "series": [{"name": series_name, "values": values}]}


def histogram_chart(
    title: str,
    values: list[float],
    *,
    bins: int = 10,
) -> dict[str, Any]:
    """Histograma de distribución de frecuencias."""
    if not values:
        return {"type": "histogram", "title": title, "labels": [], "series": []}
    mn, mx = min(values), max(values)
    if mn == mx:
        return {
            "type": "histogram", "title": title, "labels": [str(mn)],
            "series": [{"name": "Frecuencia", "values": [float(len(values))]}],
        }
    width = (mx - mn) / bins
    buckets: list[float] = [0.0] * bins
    bucket_labels: list[str] = []
    for i in range(bins):
        lo = mn + i * width
        hi = mn + (i + 1) * width
        bucket_labels.append(f"{lo:.1f}–{hi:.1f}")
        buckets[i] = float(sum(1 for v in values if lo <= v < hi))
    # Last bucket is inclusive
    buckets[-1] += sum(1 for v in values if v == mx)
    return {
        "type": "histogram", "title": title, "labels": bucket_labels,
        "series": [{"name": "Frecuencia", "values": buckets}],
    }


def scatter_chart(
    title: str,
    x_values: list[float],
    y_values: list[float],
    *,
    x_label: str = "X",
    y_label: str = "Y",
    point_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Gráfico de dispersión para correlaciones."""
    return {
        "type": "scatter",
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "labels": point_labels or [str(i) for i in range(len(x_values))],
        "series": [{"name": y_label, "x": x_values, "values": y_values}],
    }


def select_chart_type(
    labels: list[str],
    num_series: int = 1,
    *,
    hint: str | None = None,
) -> ChartType:
    """Selecciona el tipo de gráfico más apropiado según los datos y el contexto.

    Reglas semánticas:
      - Serie temporal + 1 serie → line
      - Serie temporal + N series → line (multi-series comparison)
      - Pocas categorías (≤6) + 1 serie → donut
      - Muchas categorías + 1 serie → bar (o horizontal_bar si >12)
      - N categorías + N series → grouped_bar
      - Hint 'ranking' → horizontal_bar
      - Hint 'composition' → stacked_bar o donut
      - Hint 'distribution' → histogram
      - Hint 'correlation' → scatter
    """
    if hint == "distribution":
        return "histogram"
    if hint == "correlation":
        return "scatter"
    if hint == "ranking" or (not _is_time_like(labels) and len(labels) > 12):
        return "horizontal_bar"
    if _is_time_like(labels):
        return "line"
    if hint in ("composition", "share"):
        return "donut" if len(labels) <= 8 else "stacked_bar"
    if num_series > 1:
        return "grouped_bar"
    if len(labels) <= 6:
        return "donut"
    return "bar"
