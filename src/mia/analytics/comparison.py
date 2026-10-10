"""ComparisonEngine — comparación universal A vs B (entidades, periodos, métricas).

Permite comparar:
  - dos grupos (departamentos, puestos, personas)
  - dos periodos (este año vs el pasado, Q1 vs Q2)
  - múltiples grupos a la vez

El resultado es un ComparisonResult con:
  - tabla de diferencias
  - ganador/peor por métrica
  - insights automáticos

Los valores vienen de código determinista; el LLM solo los narra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """Comparación de una métrica entre dos entidades."""

    metric: str
    label_a: str
    value_a: float | None
    label_b: str
    value_b: float | None
    unit: str = ""
    higher_is_better: bool | None = None
    """None = neutral, True = mayor es mejor, False = menor es mejor."""

    @property
    def absolute_diff(self) -> float | None:
        if self.value_a is None or self.value_b is None:
            return None
        return round(self.value_a - self.value_b, 4)

    @property
    def pct_diff(self) -> float | None:
        if self.value_a is None or self.value_b is None:
            return None
        if self.value_b == 0:
            return None
        return round((self.value_a - self.value_b) / abs(self.value_b) * 100, 2)

    @property
    def winner(self) -> str | None:
        if self.value_a is None or self.value_b is None:
            return None
        if self.higher_is_better is True:
            if self.value_a > self.value_b:
                return self.label_a
            elif self.value_b > self.value_a:
                return self.label_b
        elif self.higher_is_better is False:
            if self.value_a < self.value_b:
                return self.label_a
            elif self.value_b < self.value_a:
                return self.label_b
        return None  # neutral or tie

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            self.label_a: self.value_a,
            self.label_b: self.value_b,
            "diff_absolute": self.absolute_diff,
            "diff_pct": self.pct_diff,
            "winner": self.winner,
            "unit": self.unit,
        }


@dataclass
class ComparisonResult:
    """Resultado completo de una comparación multi-métrica."""

    label_a: str
    label_b: str
    metrics: list[MetricComparison] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        rows = [m.to_dict() for m in self.metrics]
        wins_a = sum(1 for m in self.metrics if m.winner == self.label_a)
        wins_b = sum(1 for m in self.metrics if m.winner == self.label_b)
        return {
            "label_a": self.label_a,
            "label_b": self.label_b,
            "metrics": rows,
            "wins": {self.label_a: wins_a, self.label_b: wins_b},
            "notes": self.notes,
        }

    def to_table(self) -> dict[str, Any]:
        """Representación tabular para el frontend."""
        return {
            "type": "table",
            "title": f"{self.label_a} vs {self.label_b}",
            "columns": ["Métrica", self.label_a, self.label_b, "Diferencia", "% Diferencia", "Mejor"],
            "rows": [
                [
                    m.metric,
                    _fmt(m.value_a, m.unit),
                    _fmt(m.value_b, m.unit),
                    _fmt_diff(m.absolute_diff, m.unit),
                    f"{m.pct_diff:+.1f}%" if m.pct_diff is not None else "—",
                    m.winner or "—",
                ]
                for m in self.metrics
            ],
        }

    def key_insights(self) -> list[str]:
        """Genera 2–5 frases clave sobre la comparación."""
        lines = []
        for m in self.metrics:
            if m.winner and m.pct_diff is not None and abs(m.pct_diff) >= 5:
                direction = "mayor" if m.absolute_diff and m.absolute_diff > 0 else "menor"
                lines.append(
                    f"{m.winner} tiene {direction} {m.metric} "
                    f"({'+' if m.pct_diff > 0 else ''}{m.pct_diff:.1f}%)."
                )
        return lines[:5]


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}" if isinstance(v, float) else str(v)
    return f"{s} {unit}".strip() if unit else s


def _fmt_diff(d: float | None, unit: str) -> str:
    if d is None:
        return "—"
    s = f"{d:+,.2f}"
    return f"{s} {unit}".strip() if unit else s


# ------------------------------------------------------------------ multi-group
@dataclass
class MultiGroupComparison:
    """Comparación de N grupos sobre las mismas métricas."""

    groups: dict[str, dict[str, float | None]]
    """groups[group_name][metric_name] = value"""
    metric_units: dict[str, str] = field(default_factory=dict)
    metric_higher_is_better: dict[str, bool | None] = field(default_factory=dict)

    def to_table(self) -> dict[str, Any]:
        metrics = list(dict.fromkeys(m for g in self.groups.values() for m in g))
        group_names = list(self.groups.keys())
        columns = ["Métrica", *group_names, "Mejor", "Peor"]
        rows = []
        for metric in metrics:
            unit = self.metric_units.get(metric, "")
            hib = self.metric_higher_is_better.get(metric)
            values = [(g, self.groups[g].get(metric)) for g in group_names]
            valid = [(g, v) for g, v in values if v is not None]
            if valid and hib is True:
                best = max(valid, key=lambda x: x[1])
                worst = min(valid, key=lambda x: x[1])
            elif valid and hib is False:
                best = min(valid, key=lambda x: x[1])
                worst = max(valid, key=lambda x: x[1])
            else:
                best = worst = (None, None)
            row = [metric] + [_fmt(self.groups[g].get(metric), unit) for g in group_names]
            row += [best[0] or "—", worst[0] or "—"]
            rows.append(row)
        return {"type": "table", "title": "Comparativa de grupos", "columns": columns, "rows": rows}

    def ranking(self, metric: str, *, descending: bool = True) -> list[dict[str, Any]]:
        """Ranking de grupos por una métrica."""
        items = [(g, self.groups[g].get(metric)) for g in self.groups]
        valid = [(g, v) for g, v in items if v is not None]
        sorted_items = sorted(valid, key=lambda x: x[1], reverse=descending)
        unit = self.metric_units.get(metric, "")
        return [
            {"rank": i + 1, "group": g, "value": v, "unit": unit}
            for i, (g, v) in enumerate(sorted_items)
        ]
