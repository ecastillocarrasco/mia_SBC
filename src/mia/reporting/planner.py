"""ReportPlanner — traduce una petición en lenguaje natural en un ``ReportPlan`` estructurado y
validado (Bloque II, Fase B: "planes estructurados y validación").

Deliberadamente determinista en esta fase: resuelve la petición contra el catálogo semántico existente
(``mia.query.fields.field_registry``) y el motor de periodos (``mia.query.period.period_engine``), sin
llamar a ningún LLM. La interpretación asistida por LLM de peticiones más ambiguas es la Fase F
("Integración LLM") — este planificador es la base DETERMINISTA y VALIDABLE sobre la que esa fase se
apoyará, nunca al revés: ningún paso aquí decide permisos ni k-anonimato a partir de texto generado por
un modelo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from mia.auth import Permission, UserContext
from mia.query.fields import FieldDef, SemanticFieldRegistry, field_registry
from mia.query.period import PeriodEngine, ResolvedPeriod, period_engine

_MAX_PERIOD_WINDOW = 8
"""Ninguna expresión de periodo reconocida por PeriodEngine supera las 8 palabras («el tercer trimestre
de 2026» son 5) — una ventana mayor solo añadiría coincidencias falsas sin ganar cobertura real."""


def _extract_period(text: str, periods: PeriodEngine, today: date | None) -> ResolvedPeriod | None:
    """``PeriodEngine.resolve()`` espera una expresión de periodo ya aislada (ver sus propios patrones,
    casi todos anclados al principio de la cadena) — una petición de informe real la trae incrustada
    en una frase más larga («... de los últimos tres años, desglosado por...»). Se prueban todas las
    sub-frases contiguas de la petición, de más larga a más corta, y se usa la primera que el motor de
    periodos reconozca — evita que el planificador dependa de que el texto llegue "ya recortado"."""
    tokens = [t.rstrip(".") for t in re.findall(r"[^\s,;:]+", text) if t.rstrip(".")]
    for window in range(min(_MAX_PERIOD_WINDOW, len(tokens)), 0, -1):
        for start in range(len(tokens) - window + 1):
            candidate = " ".join(tokens[start : start + window])
            resolved = periods.resolve(candidate, today=today)
            if resolved is not None:
                return resolved
    return None


_COMPARE_HINTS = (
    "compara",
    "comparacion",
    "comparativa",
    "evolucion",
    "evolución",
    "tendencia",
    "variacion",
    "variación",
    "interanual",
    "respecto a",
    "frente a",
    "vs",
)
_DIMENSION_ONLY_OPS = frozenset({"count", "distribution"})
_FORMAT_HINTS: dict[str, tuple[str, ...]] = {
    "pdf": ("pdf",),
    "xlsx": ("excel", "xlsx", "hoja de calculo", "hoja de cálculo"),
    "pptx": ("powerpoint", "pptx", "presentacion", "presentación", "diapositivas"),
}


def _is_dimension_like(fd: FieldDef) -> bool:
    """Un campo es más dimensión que métrica si solo admite agrupar/contar, nunca promediar/sumar."""
    return set(fd.agg_ops) <= _DIMENSION_ONLY_OPS


@dataclass(frozen=True, slots=True)
class PlannedMetric:
    field: FieldDef
    granted: bool
    """False si el usuario no tiene el permiso que exige ``field.permission`` — nunca se incluye en la
    ejecución real, solo se conserva aquí para que el aviso al usuario sea explícito, no un campo que
    "desaparece" sin explicación."""
    requires_protected_route: bool
    """True si ``field.min_group`` está definido (hoy, solo nóminas): la ejecución de este plan NO debe
    consultar la fuente directamente, debe delegar en la herramienta de dominio ya auditada que aplica
    el umbral de k-anonimato (p. ej. ``ranking_salarial``/``estadisticas_salariales``)."""


@dataclass(frozen=True, slots=True)
class ReportPlan:
    raw_request: str
    metrics: tuple[PlannedMetric, ...] = ()
    dimensions: tuple[FieldDef, ...] = ()
    period: ResolvedPeriod | None = None
    compare: bool = False
    requested_format: str | None = None
    """«pdf» | «xlsx» | «pptx» | None si la petición no especifica formato."""
    warnings: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Ningún campo reconocido: ni una métrica ni una dimensión. El planificador no debe inventar
        un informe genérico cuando no entendió la petición — quien lo use debe tratarlo como "no se
        pudo planificar", nunca como "informe vacío válido"."""
        return not self.metrics and not self.dimensions

    @property
    def granted_metrics(self) -> tuple[PlannedMetric, ...]:
        return tuple(m for m in self.metrics if m.granted)

    @property
    def denied_metrics(self) -> tuple[PlannedMetric, ...]:
        return tuple(m for m in self.metrics if not m.granted)


def _detect_format(norm: str) -> str | None:
    for fmt, hints in _FORMAT_HINTS.items():
        if any(h in norm for h in hints):
            return fmt
    return None


class ReportPlanner:
    def __init__(
        self,
        registry: SemanticFieldRegistry = field_registry,
        periods: PeriodEngine = period_engine,
    ) -> None:
        self._registry = registry
        self._periods = periods

    def plan(self, request: str, *, user: UserContext, today: date | None = None) -> ReportPlan:
        from mia.text import normalize_key  # noqa: PLC0415 — evita un ciclo si mia.text crece

        norm = normalize_key(request)
        warnings: list[str] = []

        resolved_period = _extract_period(request, self._periods, today)
        if resolved_period is None:
            warnings.append(
                "No se ha reconocido ningún periodo explícito en la petición; la ejecución deberá "
                "aplicar un periodo por defecto y dejarlo explícito en el informe, nunca asumirlo en "
                "silencio."
            )

        fields_found = self._registry.resolve_all(request)
        metrics: list[PlannedMetric] = []
        dimensions: list[FieldDef] = []
        for fd in fields_found:
            if _is_dimension_like(fd):
                dimensions.append(fd)
                continue
            granted = True
            if fd.permission:
                try:
                    granted = user.has(Permission[fd.permission])
                except KeyError:  # pragma: no cover — catálogo con un nombre de permiso inválido
                    granted = False
                    warnings.append(
                        f"El campo «{fd.name}» declara un permiso desconocido ({fd.permission!r}) en "
                        "el catálogo; se trata como no autorizado por seguridad."
                    )
            if not granted:
                warnings.append(
                    f"El usuario no tiene permiso para «{fd.name}»: se excluye del plan, no se "
                    "sustituye por un valor ni se omite en silencio."
                )
            metrics.append(PlannedMetric(field=fd, granted=granted, requires_protected_route=fd.min_group is not None))

        if not metrics and not dimensions:
            warnings.append(
                "No se ha reconocido ningún campo del catálogo semántico en la petición: no se puede "
                "construir un plan a partir de este texto."
            )

        return ReportPlan(
            raw_request=request,
            metrics=tuple(metrics),
            dimensions=tuple(dimensions),
            period=resolved_period,
            compare=any(hint in norm for hint in _COMPARE_HINTS),
            requested_format=_detect_format(norm),
            warnings=tuple(warnings),
        )


planner: ReportPlanner = ReportPlanner()
