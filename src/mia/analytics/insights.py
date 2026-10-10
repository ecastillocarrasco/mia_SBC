"""InsightEngine — detección automática de hechos relevantes en un dataset.

El LLM redacta los insights, pero los VALORES vienen siempre de aquí (código
determinista). El engine devuelve una lista de Insight con:
  - tipo (categoría del hallazgo)
  - importancia (0–1, para ordenar)
  - datos numéricos verificables
  - plantilla de texto que el LLM puede usar literalmente

No se inventan datos ni se usan valores del LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mia.analytics.stats import (
    TimePoint,
    detect_abrupt_changes,
    detect_outliers,
    time_series_stats,
)

InsightType = Literal[
    "max_value",
    "min_value",
    "highest_increase",
    "highest_drop",
    "outlier",
    "trend_up",
    "trend_down",
    "trend_flat",
    "abrupt_change",
    "concentration",
    "data_quality",
    "comparison_winner",
    "comparison_loser",
    "milestone",
]


@dataclass
class Insight:
    type: InsightType
    importance: float
    """0–1, siendo 1 el más importante."""
    text: str
    """Frase lista para mostrar al usuario (en español)."""
    data: dict[str, Any] = field(default_factory=dict)
    """Valores numéricos de soporte (para trazabilidad)."""


class InsightEngine:
    """Detecta insights a partir de series temporales, comparaciones y distribuciones."""

    # ------------------------------------------------------------------ API
    def from_time_series(
        self,
        points: list[TimePoint],
        *,
        label: str = "métrica",
        unit: str = "",
    ) -> list[Insight]:
        """Genera insights para una serie temporal."""
        stats = time_series_stats(points)
        insights: list[Insight] = []
        if stats.get("count", 0) < 2:
            return []

        # Tendencia
        trend_info = stats.get("trend", {})
        if trend_info.get("direction") == "increasing":
            insights.append(Insight(
                type="trend_up",
                importance=0.7,
                text=f"{label.capitalize()} muestra tendencia creciente en el periodo analizado.",
                data={"slope": trend_info.get("slope_per_period")},
            ))
        elif trend_info.get("direction") == "decreasing":
            insights.append(Insight(
                type="trend_down",
                importance=0.7,
                text=f"{label.capitalize()} muestra tendencia decreciente en el periodo analizado.",
                data={"slope": trend_info.get("slope_per_period")},
            ))

        # Cambio total primero→último
        total_change = stats.get("total_change", {})
        pct = total_change.get("pct")
        if pct is not None and abs(pct) >= 5:
            direction = "aumentó" if pct > 0 else "disminuyó"
            insights.append(Insight(
                type="highest_increase" if pct > 0 else "highest_drop",
                importance=min(0.9, abs(pct) / 100),
                text=(
                    f"{label.capitalize()} {direction} un {abs(pct):.1f}% "
                    f"entre {stats.get('first', {}).get('label', '')} "
                    f"y {stats.get('last', {}).get('label', '')} "
                    f"({total_change.get('absolute', 0):+.2f}{(' ' + unit) if unit else ''})."
                ),
                data=total_change,
            ))

        # Máximo y mínimo
        mx = stats.get("max", {})
        mn = stats.get("min", {})
        if mx.get("label"):
            insights.append(Insight(
                type="max_value",
                importance=0.5,
                text=f"El valor más alto se registró en {mx['label']}: {mx['value']}{(' ' + unit) if unit else ''}.",
                data=mx,
            ))
        if mn.get("label") and mn.get("label") != mx.get("label"):
            insights.append(Insight(
                type="min_value",
                importance=0.4,
                text=f"El valor más bajo se registró en {mn['label']}: {mn['value']}{(' ' + unit) if unit else ''}.",
                data=mn,
            ))

        # Mayor incremento puntual
        big_inc = stats.get("biggest_increase", {})
        big_drop = stats.get("biggest_drop", {})
        if big_inc and abs(big_inc.get("pct", 0) or 0) >= 10:
            insights.append(Insight(
                type="abrupt_change",
                importance=0.8,
                text=(
                    f"Mayor incremento entre {big_inc.get('from')} y {big_inc.get('to')}: "
                    f"+{big_inc.get('pct', 0):.1f}%."
                ),
                data=big_inc,
            ))
        if big_drop and abs(big_drop.get("pct", 0) or 0) >= 10:
            insights.append(Insight(
                type="abrupt_change",
                importance=0.8,
                text=(
                    f"Mayor caída entre {big_drop.get('from')} y {big_drop.get('to')}: "
                    f"{big_drop.get('pct', 0):.1f}%."
                ),
                data=big_drop,
            ))

        # Cambios bruscos
        abrupt = detect_abrupt_changes(points, threshold_pct=25.0)
        for change in abrupt[:2]:
            direction = "subió" if change["direction"] == "up" else "bajó"
            insights.append(Insight(
                type="abrupt_change",
                importance=0.75,
                text=(
                    f"Cambio brusco: {label} {direction} un {abs(change['pct_change']):.1f}% "
                    f"entre {change['label_from']} y {change['label_to']}."
                ),
                data=change,
            ))

        return sorted(insights, key=lambda x: -x.importance)

    def from_distribution(
        self,
        groups: dict[str, float],
        *,
        label: str = "grupo",
        metric: str = "valor",
        unit: str = "",
    ) -> list[Insight]:
        """Genera insights a partir de una distribución por grupos (p. ej. por departamento)."""
        if not groups:
            return []
        insights: list[Insight] = []
        items = sorted(groups.items(), key=lambda x: -x[1])
        total = sum(v for v in groups.values() if v is not None)
        n = len(items)

        best_k, best_v = items[0]
        worst_k, worst_v = items[-1]

        insights.append(Insight(
            type="max_value",
            importance=0.8,
            text=f"{best_k} lidera con el mayor {metric}: {best_v}{(' ' + unit) if unit else ''}.",
            data={"group": best_k, "value": best_v},
        ))
        if n > 1:
            insights.append(Insight(
                type="min_value",
                importance=0.6,
                text=f"{worst_k} tiene el menor {metric}: {worst_v}{(' ' + unit) if unit else ''}.",
                data={"group": worst_k, "value": worst_v},
            ))

        # Concentración: top-1 representa > 40% del total
        if total > 0 and best_v / total > 0.40:
            pct = round(best_v / total * 100, 1)
            insights.append(Insight(
                type="concentration",
                importance=0.7,
                text=f"{best_k} concentra el {pct}% del total de {metric}.",
                data={"group": best_k, "pct": pct},
            ))

        # Outlier estadístico
        if n >= 4:
            values = [v for _, v in items if v is not None]
            labels = [k for k, v in items if v is not None]
            out = detect_outliers(values, method="iqr", labels=labels)
            for o in out.get("outliers", [])[:2]:
                direction = "alta" if o.get("direction") == "high" else "baja"
                insights.append(Insight(
                    type="outlier",
                    importance=0.75,
                    text=(
                        f"{o['label']} es un valor atípico ({direction}): "
                        f"{o['value']}{(' ' + unit) if unit else ''} (fuera del rango IQR)."
                    ),
                    data=o,
                ))

        return sorted(insights, key=lambda x: -x.importance)

    def from_comparison(
        self,
        a_label: str,
        a_value: float,
        b_label: str,
        b_value: float,
        *,
        metric: str = "valor",
        unit: str = "",
        higher_is_better: bool | None = None,
    ) -> list[Insight]:
        """Genera insights de una comparación A vs B."""
        if a_value is None or b_value is None:
            return []
        diff = a_value - b_value
        pct = (diff / abs(b_value) * 100) if b_value != 0 else None
        insights: list[Insight] = []

        winner = a_label if diff > 0 else (b_label if diff < 0 else None)
        loser = b_label if diff > 0 else (a_label if diff < 0 else None)

        if winner:
            insights.append(Insight(
                type="comparison_winner",
                importance=0.8,
                text=(
                    f"{winner} tiene mayor {metric} que {loser}: "
                    f"{a_value}{(' ' + unit) if unit else ''} vs "
                    f"{b_value}{(' ' + unit) if unit else ''} "
                    f"({'+' if diff > 0 else ''}{diff:.2f}, "
                    f"{pct:+.1f}% {'más' if diff > 0 else 'menos'})."
                    if pct is not None else
                    f"{winner} tiene mayor {metric} que {loser}."
                ),
                data={"a": a_value, "b": b_value, "diff": diff, "pct": pct},
            ))

        return insights

    def top_insights(
        self, insights: list[Insight], n: int = 5
    ) -> list[dict[str, Any]]:
        """Devuelve los N insights más importantes como dicts serializables."""
        sorted_ins = sorted(insights, key=lambda x: -x.importance)
        return [
            {"type": i.type, "importance": i.importance, "text": i.text, "data": i.data}
            for i in sorted_ins[:n]
        ]
