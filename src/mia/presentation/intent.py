"""Clasificación de intención de presentación para mIA.

Separa la intención del usuario (qué quiere) de los datos disponibles (qué hay).
Determinista, sin LLM, coste cero en tiempo de ejecución.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class PresentationIntent(StrEnum):
    DIRECT_LOOKUP = "direct_lookup"
    OPERATIONAL_LOOKUP = "operational_lookup"
    LIST = "list"
    COMPARISON = "comparison"
    ANALYSIS = "analysis"
    EXECUTIVE_ANALYSIS = "executive_analysis"
    REPORT = "report"


class ResponseDepth(StrEnum):
    MINIMAL = "minimal"
    DIRECT = "direct"
    DETAILED = "detailed"
    ANALYTICAL = "analytical"
    EXECUTIVE = "executive"


@dataclass(frozen=True, slots=True)
class QueryAnalysis:
    presentation_intent: PresentationIntent
    response_depth: ResponseDepth
    requested_output: frozenset[str]
    comparison_requested: bool
    analytics_requested: bool
    summary_requested: bool
    temporal_scope: str  # "current_instant" | "today" | "period" | "unspecified"


# ── Patterns ─────────────────────────────────────────────────────────────────

_COMPARISON_RE = re.compile(
    r"\bcompara\b|\bversus\b|\bvs\b|\bfrente\s+a\b"
    r"|\bdiferencia(?:s)?\s+(?:entre|con)\b"
    r"|\bqué\s+departamento\s+(?:está|tiene)\s+(?:más|mejor|peor)\b"
    r"|\bmejor\s+que\b|\bpeor\s+que\b|\bmás\s+que\b",
    re.IGNORECASE,
)

_ANALYTICS_RE = re.compile(
    r"\banaliz[a-z]*\b|\btendencia\b|\bevolución\b"
    r"|\bcómo\s+(?:va|vamos|están?)\b|\bqué\s+está\s+pasando\b"
    r"|\bhay\s+algo\s+preocupante\b|\banomalí[a-z]*\b"
    r"|\binsights?\b|\bconclusiones?\b|\bqué\s+debería\s+preocup\b"
    r"|\bsituación\s+(?:de|del)\b|\bvisión\s+ejecutiva\b",
    re.IGNORECASE,
)

_REPORT_RE = re.compile(r"\binforme\b|\breporte\b|\bdocumento\b", re.IGNORECASE)

_EXECUTIVE_RE = re.compile(
    r"\bcómo\s+va\s+rrhh\b|\bcómo\s+vamos\b|\bvisión\s+ejecutiva\b"
    r"|\bresumen\s+ejecutivo\b|\bdashboard\b",
    re.IGNORECASE,
)

_TEMPORAL_NOW_RE = re.compile(
    r"\bahora\b|\bahora\s+mismo\b|\ben\s+este\s+momento\b|\bactualmente\b"
    r"|\bquiénes?\s+están?\s+trabaj|\bquién\s+está\s+trabaj",
    re.IGNORECASE,
)

_PEOPLE_RE = re.compile(
    r"\bquiénes?\b|\bqué\s+personas\b|\bqué\s+empleados?\b|\blistar\s+personas\b",
    re.IGNORECASE,
)

_COUNT_RE = re.compile(
    r"\bcuántos?\b|\bcuántas?\b|\bnúmero\s+de\b|\btotal\s+de\b",
    re.IGNORECASE,
)

_LIST_RE = re.compile(r"\blista\b|\blistado\b|\benumera\b", re.IGNORECASE)
_CHART_RE = re.compile(r"\bgráfico\b|\bgráfica\b|\bvisualiz[a-z]*\b", re.IGNORECASE)
# Raíz "resum"/"resúm" + cualquier terminación: cubre resumen, resúmenes, resume, resúmeme,
# resumiendo… con o sin tilde (un fallo de tecleo frecuente es omitirla) — nunca una lista cerrada
# de formas exactas, porque el usuario puede pedirlo de muchas maneras distintas.
_SUMMARY_RE = re.compile(r"\bres[uú]m\w*\b", re.IGNORECASE)


def classify_query(query: str) -> QueryAnalysis:
    """Clasifica la intención de presentación sin llamadas al LLM."""
    comparison_requested = bool(_COMPARISON_RE.search(query))
    analytics_requested = bool(_ANALYTICS_RE.search(query))
    summary_requested = bool(_SUMMARY_RE.search(query))
    temporal_scope = "current_instant" if _TEMPORAL_NOW_RE.search(query) else "unspecified"

    outputs: set[str] = set()
    if _PEOPLE_RE.search(query) or temporal_scope == "current_instant":
        outputs.add("people")
    if _COUNT_RE.search(query):
        outputs.add("count")
    if _LIST_RE.search(query):
        outputs.add("list")
    if comparison_requested:
        outputs.add("comparison")
    if _CHART_RE.search(query):
        outputs.add("chart")
    if analytics_requested:
        outputs.add("analysis")
    if summary_requested:
        outputs.add("summary")
    if _REPORT_RE.search(query):
        outputs.add("report")
    if not outputs:
        outputs.add("answer")

    # Priority: report > executive > comparison > analysis > operational > count > list > default
    if _REPORT_RE.search(query):
        intent = PresentationIntent.REPORT
        depth = ResponseDepth.EXECUTIVE
    elif _EXECUTIVE_RE.search(query):
        intent = PresentationIntent.EXECUTIVE_ANALYSIS
        depth = ResponseDepth.EXECUTIVE
    elif comparison_requested:
        intent = PresentationIntent.COMPARISON
        depth = ResponseDepth.DETAILED
    elif analytics_requested:
        intent = PresentationIntent.ANALYSIS
        depth = ResponseDepth.ANALYTICAL
    elif temporal_scope == "current_instant" or _PEOPLE_RE.search(query):
        intent = PresentationIntent.OPERATIONAL_LOOKUP
        depth = ResponseDepth.DIRECT
    elif _COUNT_RE.search(query):
        intent = PresentationIntent.DIRECT_LOOKUP
        depth = ResponseDepth.MINIMAL
    elif _LIST_RE.search(query):
        intent = PresentationIntent.LIST
        depth = ResponseDepth.DIRECT
    else:
        intent = PresentationIntent.DIRECT_LOOKUP
        depth = ResponseDepth.DIRECT

    return QueryAnalysis(
        presentation_intent=intent,
        response_depth=depth,
        requested_output=frozenset(outputs),
        comparison_requested=comparison_requested,
        analytics_requested=analytics_requested,
        summary_requested=summary_requested,
        temporal_scope=temporal_scope,
    )


# ── LLM hint ─────────────────────────────────────────────────────────────────

_DIRECT_INTENTS = frozenset(
    {
        PresentationIntent.OPERATIONAL_LOOKUP,
        PresentationIntent.DIRECT_LOOKUP,
        PresentationIntent.LIST,
    }
)


def build_presentation_hint(qa: QueryAnalysis) -> str:
    """Genera pista contextual para el LLM basada en la intención detectada.

    Va en el bloque <contexto_del_turno> para guiar la selección de herramientas
    y el texto de respuesta sin llamadas adicionales al LLM.
    """
    lines: list[str] = []

    if qa.temporal_scope == "current_instant":
        lines.append("Hora de referencia: el instante actual (turno activo ahora mismo).")

    if not qa.comparison_requested:
        lines.append("No es petición de comparación: no invoques herramientas de comparativa.")
    if not qa.analytics_requested:
        lines.append("No es petición de análisis: no invoques herramientas de análisis ni predicción.")

    if "people" in qa.requested_output:
        lines.append(
            "Si una herramienta devuelve una lista de personas, "
            "ésta se muestra automáticamente al usuario. "
            "No ofrezcas «¿quieres ver quiénes son?» ni solicitudes similares "
            "cuando los datos ya son visibles en la presentación."
        )

    if qa.presentation_intent in _DIRECT_INTENTS and not qa.summary_requested:
        lines.append("Responde directamente y de forma breve: no añadas análisis, comparativas ni distribuciones.")

    if qa.summary_requested:
        lines.append(
            "Es una petición de resumen: sintetiza el contenido real (de qué trata, quién interviene, qué "
            "destaca) con tus propias palabras. No es una respuesta completa decir que los datos ya están "
            "en la tabla/pantalla ni limitarte a señalar dónde mirar — eso es independiente del aviso "
            "general de no repetir una tabla entera en texto."
        )

    return "\n".join(lines)
