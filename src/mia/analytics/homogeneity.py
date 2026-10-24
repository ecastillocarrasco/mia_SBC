"""Comprobaciones de homogeneidad antes de comparar (Bloque II, sección 8: "Motor de comparativas
homogéneas").

Nunca calcula la comparación en sí (eso es ``comparison.py``): solo decide si dos periodos, dos
poblaciones, dos unidades/granularidades o un denominador son aptos para compararse, y explica por qué
no cuando no lo son.

Tres niveles de severidad (ajuste de Fase D, condición obligatoria 2 de la aprobación): "informativas,
problemas de calidad de datos y errores que deben impedir la generación de conclusiones":
  - ``info``: dato relevante para quien lea el informe, no afecta a la validez de la comparación.
  - ``data_quality``: la comparación puede seguir construyéndose, pero su interpretación debe matizarse
    (p. ej. duraciones muy distintas) — se muestra SIEMPRE junto al resultado, nunca en silencio.
  - ``blocker``: la comparación no debe construirse en absoluto (sección 8: "no emitir conclusiones
    cuando los datos sean incompatibles").

Cada ``HomogeneityIssue`` lleva código, fuente y contexto para poder mostrarse como un
``Block(kind="warnings")`` trazable (ver ``mia.reporting.document.warnings_block``), no solo
como texto suelto.

Deliberadamente no asume cosas que ``ResolvedPeriod`` (``mia.query.period``) no sabe: no tiene
granularidad explícita, así que la detección de "periodo parcial" se basa en si el periodo llega hasta
hoy (``today``) — un periodo que termina antes de hoy se trata como cerrado, uno que llega hasta hoy
como potencialmente todavía en curso. El llamador puede pasar explícitamente ``today`` para que el
resultado sea determinista en las pruebas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from mia.query.period import ResolvedPeriod

Severity = Literal["info", "data_quality", "blocker"]
_SOURCE = "mia.analytics.homogeneity"


@dataclass(frozen=True, slots=True)
class HomogeneityIssue:
    severity: Severity
    code: str
    message: str
    source: str = _SOURCE
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "context": dict(self.context),
        }


def _span_days(period: ResolvedPeriod) -> int:
    return (period.end - period.start).days + 1


def check_period_pair(
    a: ResolvedPeriod, b: ResolvedPeriod, *, today: date | None = None
) -> list[HomogeneityIssue]:
    """¿Son estos dos periodos aptos para compararse entre sí?"""
    ref = today or date.today()
    issues: list[HomogeneityIssue] = []

    a_ongoing = a.end >= ref
    b_ongoing = b.end >= ref
    if a_ongoing != b_ongoing:
        ongoing, closed = (a, b) if a_ongoing else (b, a)
        issues.append(
            HomogeneityIssue(
                "blocker",
                "PERIOD_PARTIAL_VS_CLOSED",
                f"«{ongoing.label}» todavía está en curso (llega hasta hoy) mientras que «{closed.label}» "
                "ya cerró por completo: compararlos como equivalentes daría una conclusión engañosa "
                "(un periodo parcial frente a uno completo).",
                context={"ongoing": ongoing.label, "closed": closed.label, "today": ref.isoformat()},
            )
        )

    days_a, days_b = _span_days(a), _span_days(b)
    if days_a > 0 and days_b > 0:
        ratio = max(days_a, days_b) / min(days_a, days_b)
        if ratio >= 1.5:
            issues.append(
                HomogeneityIssue(
                    "data_quality",
                    "PERIOD_DURATION_MISMATCH",
                    f"«{a.label}» ({days_a} días) y «{b.label}» ({days_b} días) tienen duraciones muy "
                    "distintas: comparar totales (en vez de medias o tasas) podría ser engañoso.",
                    context={"days_a": days_a, "days_b": days_b, "ratio": round(ratio, 2)},
                )
            )

    return issues


def check_populations(
    count_a: int, count_b: int, *, label_a: str, label_b: str
) -> list[HomogeneityIssue]:
    """¿Hay datos suficientes en ambos lados para que la comparación signifique algo?"""
    issues: list[HomogeneityIssue] = []
    if count_a == 0 or count_b == 0:
        empty = label_a if count_a == 0 else label_b
        issues.append(
            HomogeneityIssue(
                "blocker",
                "POPULATION_EMPTY",
                f"«{empty}» no tiene ningún registro en este periodo: no hay nada que comparar.",
                context={"label_a": label_a, "count_a": count_a, "label_b": label_b, "count_b": count_b},
            )
        )
    return issues


def check_denominator(value: float | None, *, context: str) -> HomogeneityIssue | None:
    """¿Se puede calcular una variación porcentual sobre este valor? (section 8: "no calcular
    variaciones porcentuales sobre denominadores inválidos")."""
    if value is None or value == 0:
        return HomogeneityIssue(
            "blocker",
            "DENOMINATOR_INVALID",
            f"No se puede calcular la variación porcentual de «{context}»: el denominador es cero o desconocido.",
            context={"metric": context, "value": value},
        )
    return None


def check_units(
    unit_a: str, unit_b: str, *, label_a: str, label_b: str
) -> list[HomogeneityIssue]:
    """¿Tienen las dos métricas la misma unidad? Comparar € contra días, o % contra horas, no tiene
    sentido aunque los números en sí se puedan restar."""
    if unit_a and unit_b and unit_a != unit_b:
        return [
            HomogeneityIssue(
                "blocker",
                "UNIT_MISMATCH",
                f"«{label_a}» se mide en {unit_a} y «{label_b}» en {unit_b}: no son comparables directamente.",
                context={"unit_a": unit_a, "unit_b": unit_b},
            )
        ]
    return []


def check_granularity(
    granularity_a: str, granularity_b: str, *, label_a: str, label_b: str
) -> list[HomogeneityIssue]:
    """¿Tienen las dos métricas el mismo nivel de agregación (``FieldDef.granularity``)? A diferencia de
    la unidad, una diferencia de granularidad no siempre invalida la comparación (p. ej. un total
    `per_payslip` sigue siendo comparable con otro total `per_payslip` de otro periodo) — se avisa, no
    se bloquea, salvo que el llamador decida lo contrario con el resultado."""
    if granularity_a and granularity_b and granularity_a != granularity_b:
        return [
            HomogeneityIssue(
                "data_quality",
                "GRANULARITY_MISMATCH",
                f"«{label_a}» ({granularity_a}) y «{label_b}» ({granularity_b}) no están al mismo nivel "
                "de detalle: revisa si de verdad son comparables antes de concluir algo.",
                context={"granularity_a": granularity_a, "granularity_b": granularity_b},
            )
        ]
    return []


def has_blocker(issues: list[HomogeneityIssue]) -> bool:
    return any(i.severity == "blocker" for i in issues)
