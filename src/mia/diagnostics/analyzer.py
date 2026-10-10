"""Análisis automático de trazas: detecta capability gaps, data gaps y riesgos de alucinación."""

from __future__ import annotations

import re
from typing import Any

from mia.diagnostics.models import DiagnosticIssueType, EventStage, TraceRecord

# Herramientas que interpretan presencia en tiempo real (requieren hora o franja para «ahora»)
_TEMPORAL_NOW_TOOLS = frozenset({"turnos_dia", "turnos_historico", "metricas_turnos"})

# Patrones temporales de «ahora» en la consulta del usuario
_TEMPORAL_NOW_RE = re.compile(
    r"\bahora\b|\bahora\s+mismo\b|\ben\s+este\s+momento\b|\bactualmente\b"
    r"|\bquién\s+está\s+trabaj|\bquiénes?\s+están?\s+trabaj|\bquién\s+esta\s+trabaj",
    re.IGNORECASE,
)


def analyze(record: TraceRecord) -> None:
    """Enriquece la TraceRecord con issues diagnósticos detectados automáticamente.

    Solo añade issues que no estén ya presentes (idempotente, puede llamarse
    varias veces durante el ciclo de vida de la traza).
    """
    existing_types = {i.type for i in record.issues}

    # Rendimiento
    if record.elapsed_ms and record.elapsed_ms > 10_000 and DiagnosticIssueType.PERFORMANCE_WARNING not in existing_types:
        record.issues.append(
            _issue(
                DiagnosticIssueType.PERFORMANCE_WARNING,
                f"Turno lento: {record.elapsed_ms} ms (umbral: 10 000 ms)",
                elapsed_ms=record.elapsed_ms,
            )
        )

    # Sin herramientas ejecutadas: posible routing o capability gap
    if (
        record.status == "completed"
        and not record.tools_called
        and record.domain
        and DiagnosticIssueType.CAPABILITY_MISSING not in existing_types
    ):
        # Solo marca si LLM llegó a ejecutarse (hay rounds)
        if record.llm_rounds > 0:
            record.issues.append(
                _issue(
                    DiagnosticIssueType.TOOL_NOT_SELECTED,
                    "El LLM respondió sin invocar ninguna herramienta. "
                    "Posible gap de capacidad o routing incorrecto.",
                    domain=record.domain,
                )
            )

    # Errores en herramientas
    if record.tool_errors > 0 and DiagnosticIssueType.TOOL_ERROR not in existing_types:
        record.issues.append(
            _issue(
                DiagnosticIssueType.TOOL_ERROR,
                f"{record.tool_errors} herramienta(s) fallaron durante el turno.",
                tool_errors=record.tool_errors,
            )
        )

    # Demasiadas rondas LLM (posible loop o prompt insuficiente)
    if record.llm_rounds >= 7 and DiagnosticIssueType.PERFORMANCE_WARNING not in existing_types:
        record.issues.append(
            _issue(
                DiagnosticIssueType.PERFORMANCE_WARNING,
                f"Alto número de rondas LLM: {record.llm_rounds} (máximo: 8).",
                llm_rounds=record.llm_rounds,
            )
        )

    # Restricción temporal «ahora» no propagada a la herramienta
    _detect_temporal_constraint_dropped(record, existing_types)


def _detect_temporal_constraint_dropped(record: TraceRecord, existing_types: set[str]) -> None:
    """Detecta si el usuario pidió 'ahora' pero la herramienta se invocó sin filtro de hora."""
    if DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED in existing_types:
        return
    if not _TEMPORAL_NOW_RE.search(record.query or ""):
        return
    for event in record.events:
        if event.stage != EventStage.TOOL_CALL_START:
            continue
        tool_name = event.data.get("tool", "")
        if tool_name not in _TEMPORAL_NOW_TOOLS:
            continue
        args = event.data.get("args", {})
        if args.get("hora") is None and args.get("franja") is None:
            record.issues.append(
                _issue(
                    DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED,
                    f"El usuario usó lenguaje de 'ahora' pero «{tool_name}» se invocó sin 'hora' ni 'franja'.",
                    tool=tool_name,
                    query=record.query[:120] if record.query else "",
                    args_provided=sorted(k for k, v in args.items() if v is not None),
                    missing_constraint="hora",
                    expected_behavior=f"Pasar hora=HH:MM (la hora actual) a {tool_name} para filtrar presencia",
                    now_local=record.now_local,
                )
            )


def assess(record: TraceRecord) -> dict[str, Any]:
    """Devuelve un resumen de diagnóstico automático para el panel."""
    analyze(record)
    issues = record.issues
    stages_emitted = {e.stage for e in record.events}

    # Construir análisis semántico si hay restricción temporal perdida
    temporal_issues = [i for i in issues if i.type == DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED]
    semantic_analysis = None
    if temporal_issues:
        ti = temporal_issues[0]
        d = ti.details
        semantic_analysis = {
            "user_meaning": record.query,
            "expected_semantics": f"timestamp actual = {d.get('now_local', '?')} (hora local)",
            "actual_tool": d.get("tool"),
            "actual_args": d.get("args_provided"),
            "missing_constraint": d.get("missing_constraint"),
            "possible_root_cause": DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED,
            "expected_behavior": d.get("expected_behavior"),
        }

    return {
        "tool_execution_attempted": bool(record.tools_called),
        "tools_successful": len(record.tools_called) - record.tool_errors,
        "tools_failed": record.tool_errors,
        "llm_rounds": record.llm_rounds,
        "data_available": EventStage.SQL_QUERY_COMPLETE in stages_emitted
        or EventStage.TOOL_CALL_COMPLETE in stages_emitted,
        "capability_gap": any(i.type == DiagnosticIssueType.CAPABILITY_MISSING for i in issues),
        "data_gap": any(i.type == DiagnosticIssueType.DATA_MISSING for i in issues),
        "temporal_constraint_dropped": bool(temporal_issues),
        "has_errors": record.error_count > 0,
        "has_warnings": record.warning_count > 0,
        "possible_issues": [i.to_dict() for i in issues],
        "primary_issue": _primary_issue(issues),
        "semantic_analysis": semantic_analysis,
    }


def _primary_issue(issues: list[Any]) -> str | None:
    if not issues:
        return None
    priority = [
        DiagnosticIssueType.CAPABILITY_MISSING,
        DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED,
        DiagnosticIssueType.DATA_MISSING,
        DiagnosticIssueType.TOOL_ERROR,
        DiagnosticIssueType.LLM_ERROR,
        DiagnosticIssueType.PERFORMANCE_WARNING,
        DiagnosticIssueType.TOOL_NOT_SELECTED,
    ]
    for p in priority:
        for issue in issues:
            if issue.type == p:
                return p
    return issues[0].type if issues else None


def _issue(issue_type: str, message: str, **details: Any) -> Any:
    from mia.diagnostics.models import DiagnosticIssue

    return DiagnosticIssue(type=issue_type, message=message, details=details)
