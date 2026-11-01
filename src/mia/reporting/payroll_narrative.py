"""Local payroll facts and minimized context for speculative prose; no source queries."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from mia.text import normalize_key

_CONCEPTS = {
    "coste empresa": ("coste empresarial", r"\b(?:ingresos?|netos?|brutos?|liquidos?|devengados?)\b"),
    "liquido neto": ("líquido neto de nómina", r"\b(?:ingresos?|costes?|costos?|brutos?|devengados?)\b"),
    "devengado bruto": ("devengado bruto de nómina", r"\b(?:ingresos?|costes?|costos?|netos?|liquidos?)\b"),
}


def payroll_context(summary: dict[str, Any]) -> dict[str, Any] | None:
    concept = normalize_key(summary.get("concepto_economico"))
    if concept not in _CONCEPTS:
        return None
    monthly = summary.get("total_por_mes") or {}
    values = [v for _, v in sorted(monthly.items()) if isinstance(v, int | float) and not isinstance(v, bool)]
    changes = [b - a for a, b in pairwise(values)]
    trend = "insuficiente"
    if changes:
        trend = "estable" if all(v == 0 for v in changes) else "mixta"
        if all(v >= 0 for v in changes) and any(v > 0 for v in changes):
            trend = "creciente"
        elif all(v <= 0 for v in changes) and any(v < 0 for v in changes):
            trend = "decreciente"
    return {"concepto": _CONCEPTS[concept][0], "tendencia": trend, "unidad": "EUR"}


def payroll_facts(summary: dict[str, Any], values: dict[str, float], period: str | None) -> list[dict[str, Any]]:
    context = payroll_context(summary)
    if context is None or "total_periodo" not in values:
        return []
    result = []
    for metric in ("total_periodo", "personas_del_grupo"):
        if metric not in values:
            continue
        value = values[metric]
        if metric == "total_periodo":
            amount = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            scope = f" en el periodo {period}" if period else ""
            text = f"El {context['concepto']} del grupo analizado{scope} es {amount} EUR."
        else:
            text = f"El grupo analizado comprende {value:g} personas distintas."
        result.append(
            {
                "kind": "fact",
                "text": text,
                "evidence": {
                    "metric": metric,
                    "value": value,
                    "period": period,
                    "origin": "backend",
                    "concepto_economico": summary["concepto_economico"],
                },
            }
        )
    return result


def payroll_prose(statements: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Facts are local. Reject prose with unsupported quantities or conflicting financial concepts."""
    concept = normalize_key(summary.get("concepto_economico"))
    context = payroll_context(summary)
    if context is None:
        return statements
    if context["tendencia"] == "insuficiente":
        monthly = summary.get("total_por_mes") or {}
        has_month = any(isinstance(value, int | float) and not isinstance(value, bool) for value in monthly.values())
        limitation = (
            "El periodo contiene un único mes: permite describir su coste, pero no evaluar una tendencia. "
            if has_month
            else "No hay una serie mensual disponible para evaluar una tendencia. "
        )
        return [
            {
                "kind": "interpretation",
                "text": limitation + "Estos datos no permiten determinar si los recursos económicos son suficientes.",
            },
            {
                "kind": "hypothesis",
                "text": "No se formula una hipótesis causal: faltan periodos comparables y evidencia sobre las causas.",
            },
            {
                "kind": "recommendation",
                "text": "Para estudiar la evolución, consulta al menos dos meses comparables. "
                "Para valorar suficiencia económica, aporta un presupuesto u objetivo autorizado.",
            },
        ]
    rejected = _CONCEPTS[concept][1]
    opposite = {
        "creciente": r"\b(?:disminu\w*|descens\w*|decrec\w*|reduccion)\b",
        "decreciente": r"\b(?:aument\w*|increment\w*|crecim\w*)\b",
        "estable": r"\b(?:aument\w*|disminu\w*|increment\w*|descens\w*)\b",
        "mixta": r"\b(?:gradual\w*|continu\w*|sostenid\w*)\b",
        "insuficiente": r"\b(?:tendencia|evolucion)\b",
    }[context["tendencia"]]
    return [
        s
        for s in statements
        if s.get("kind") != "fact"
        and not re.search(rejected, normalize_key(s.get("text")))
        and not re.search(r"\d", str(s.get("text", "")))
        and not (s.get("kind") == "interpretation" and re.search(opposite, normalize_key(s.get("text"))))
    ]
