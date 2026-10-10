"""Tests del módulo de clasificación de intención de presentación (mia.presentation.intent).

Cobertura de casos A–G del spec Phase 3:
A. Consulta operativa directa con "ahora" → OPERATIONAL_LOOKUP, temporal_scope=current_instant
B. Consulta de comparativa explícita → COMPARISON, comparison_requested=True
C. Consulta analítica → ANALYSIS, analytics_requested=True
D. Consulta de conteo puro → DIRECT_LOOKUP, count en requested_output
E. Consulta de listado → LIST o OPERATIONAL_LOOKUP
F. Consulta de informe/reporte → REPORT
G. Consulta sin señales específicas → DIRECT_LOOKUP (fallback)
+ Tests de build_presentation_hint()
+ Tests de suppress_comparison en summary_view()
"""
from __future__ import annotations

import pytest

from mia.presentation.intent import (
    PresentationIntent,
    QueryAnalysis,
    ResponseDepth,
    build_presentation_hint,
    classify_query,
)


# ── Caso A: consulta operativa con "ahora" ───────────────────────────────────

def test_case_a_quien_trabaja_ahora_operacional():
    qa = classify_query("quien esta trabajando ahora en restaurante y en cocina")
    assert qa.presentation_intent == PresentationIntent.OPERATIONAL_LOOKUP
    assert qa.temporal_scope == "current_instant"
    assert qa.comparison_requested is False
    assert qa.analytics_requested is False
    assert "people" in qa.requested_output


def test_case_a_ahora_mismo():
    qa = classify_query("quiénes están trabajando ahora mismo")
    assert qa.presentation_intent == PresentationIntent.OPERATIONAL_LOOKUP
    assert qa.temporal_scope == "current_instant"


def test_case_a_en_este_momento():
    qa = classify_query("dime quién está en turno en este momento")
    assert qa.temporal_scope == "current_instant"
    assert qa.presentation_intent == PresentationIntent.OPERATIONAL_LOOKUP


def test_case_a_actualmente():
    qa = classify_query("actualmente quién está trabajando en cocina")
    assert qa.temporal_scope == "current_instant"
    assert qa.presentation_intent == PresentationIntent.OPERATIONAL_LOOKUP


# ── Caso B: comparativa explícita ────────────────────────────────────────────

def test_case_b_comparativa_departamentos():
    qa = classify_query("compara el departamento de cocina con el de restaurante")
    assert qa.presentation_intent == PresentationIntent.COMPARISON
    assert qa.comparison_requested is True
    assert qa.response_depth == ResponseDepth.DETAILED
    assert "comparison" in qa.requested_output


def test_case_b_versus():
    qa = classify_query("cocina versus restaurante, qué departamento tiene más personas hoy")
    assert qa.comparison_requested is True
    assert qa.presentation_intent == PresentationIntent.COMPARISON


def test_case_b_diferencia_entre():
    qa = classify_query("diferencias entre los turnos de mañana y tarde")
    assert qa.comparison_requested is True


# ── Caso C: análisis ──────────────────────────────────────────────────────────

def test_case_c_analizar_departamento():
    qa = classify_query("analiza la cobertura del departamento de cocina esta semana")
    assert qa.presentation_intent == PresentationIntent.ANALYSIS
    assert qa.analytics_requested is True
    assert qa.response_depth == ResponseDepth.ANALYTICAL


def test_case_c_tendencia():
    qa = classify_query("cuál es la tendencia de ausencias en los últimos 30 días")
    assert qa.analytics_requested is True
    assert qa.presentation_intent == PresentationIntent.ANALYSIS


def test_case_c_hay_algo_preocupante():
    qa = classify_query("hay algo preocupante en los turnos de esta semana")
    assert qa.analytics_requested is True


# ── Caso D: conteo puro ───────────────────────────────────────────────────────

def test_case_d_cuantos():
    qa = classify_query("cuántas personas trabajan hoy")
    assert "count" in qa.requested_output


def test_case_d_total_de():
    qa = classify_query("total de empleados activos")
    assert "count" in qa.requested_output


def test_case_d_cuantas_sin_ahora_es_direct_lookup():
    qa = classify_query("cuántas personas trabajan hoy en total")
    assert qa.presentation_intent == PresentationIntent.DIRECT_LOOKUP
    assert qa.temporal_scope == "unspecified"


# ── Caso E: listado ───────────────────────────────────────────────────────────

def test_case_e_lista():
    qa = classify_query("dame la lista de personas en turno hoy")
    assert "list" in qa.requested_output


def test_case_e_quien_sin_ahora_es_operational():
    qa = classify_query("quiénes trabajan hoy en restaurante")
    assert qa.presentation_intent == PresentationIntent.OPERATIONAL_LOOKUP
    assert "people" in qa.requested_output


# ── Caso F: informe ───────────────────────────────────────────────────────────

def test_case_f_informe():
    qa = classify_query("genera un informe de los turnos de esta semana")
    assert qa.presentation_intent == PresentationIntent.REPORT
    assert qa.response_depth == ResponseDepth.EXECUTIVE
    assert "report" in qa.requested_output


def test_case_f_reporte():
    qa = classify_query("necesito el reporte mensual de ausencias")
    assert qa.presentation_intent == PresentationIntent.REPORT


# ── Caso G: fallback ──────────────────────────────────────────────────────────

def test_case_g_fallback_sin_senales():
    qa = classify_query("muéstrame los turnos de hoy")
    assert qa.presentation_intent == PresentationIntent.DIRECT_LOOKUP
    assert qa.comparison_requested is False
    assert qa.analytics_requested is False
    assert qa.temporal_scope == "unspecified"


def test_case_g_pregunta_generica():
    qa = classify_query("cuál es el turno de Ana")
    assert qa.presentation_intent == PresentationIntent.DIRECT_LOOKUP


# ── Tests de build_presentation_hint ─────────────────────────────────────────

def test_hint_no_comparativa_para_operacional():
    qa = classify_query("quien trabaja ahora")
    hint = build_presentation_hint(qa)
    assert "comparación" in hint.lower() or "comparativa" in hint.lower()
    assert "no invoques" in hint.lower()


def test_hint_no_analisis_para_operacional():
    qa = classify_query("quien trabaja ahora")
    hint = build_presentation_hint(qa)
    assert "análisis" in hint.lower()


def test_hint_people_no_ofrecer_lista():
    qa = classify_query("quiénes están trabajando ahora")
    hint = build_presentation_hint(qa)
    assert "automáticamente" in hint


def test_hint_vacio_para_analisis_puro():
    """Para consultas analíticas, no se inhibe nada."""
    qa = classify_query("analiza la cobertura del departamento de cocina")
    hint = build_presentation_hint(qa)
    # No debe bloquear análisis
    assert "no invoques herramientas de análisis" not in hint


def test_hint_vacio_para_comparativa_pura():
    """Para comparativas explícitas, no se inhibe la comparativa."""
    qa = classify_query("compara cocina con restaurante")
    hint = build_presentation_hint(qa)
    assert "no invoques herramientas de comparativa" not in hint


def test_hint_respuesta_directa_para_lookup():
    qa = classify_query("cuántas personas hay hoy")
    hint = build_presentation_hint(qa)
    assert "directamente" in hint.lower()


# ── Tests de suppress_comparison en legacy_view.summary_view ─────────────────

def test_suppress_comparison_elimina_comparativa_de_dict_of_dicts():
    from mia.api.legacy_view import summary_view

    summaries = [
        {
            "summary": {
                "contexto_del_dia": {
                    "Trabajo": {"personas": 28, "horas": 224.0},
                    "Descanso": {"personas": 5, "horas": 0.0},
                }
            }
        }
    ]
    result_suppressed = summary_view(summaries, suppress_comparison=True)
    result_normal = summary_view(summaries, suppress_comparison=False)

    assert result_suppressed["comparacion"] == []
    assert len(result_normal["comparacion"]) > 0


def test_suppress_comparison_false_por_defecto():
    from mia.api.legacy_view import summary_view

    summaries = [
        {
            "summary": {
                "resumen": {
                    "A": {"x": 1},
                    "B": {"x": 2},
                }
            }
        }
    ]
    result = summary_view(summaries)
    assert len(result["comparacion"]) > 0


def test_suppress_comparison_no_afecta_cards():
    from mia.api.legacy_view import summary_view

    summaries = [
        {
            "summary": {
                "total_seleccionado": 28,
                "contexto_del_dia": {
                    "Trabajo": {"personas": 28},
                    "Descanso": {"personas": 5},
                },
            }
        }
    ]
    result = summary_view(summaries, suppress_comparison=True)
    assert any(c["value"] == 28 for c in result["cards"])
    assert result["comparacion"] == []


def test_legacy_view_suppress_comparison():
    from mia.api.legacy_view import legacy_view

    summaries = [
        {
            "tool": "turnos_dia",
            "summary": {
                "contexto_del_dia": {
                    "Trabajo": {"personas": 28},
                    "Descanso": {"personas": 5},
                }
            },
        }
    ]
    data, _ = legacy_view([], summaries, suppress_comparison=True)
    assert "comparacion" not in data or data.get("comparacion") == []


# ── _merge_same_schema_tables ─────────────────────────────────────────────────

def _make_table(title: str, cols: list[str], rows: list[list]) -> dict:
    return {"type": "table", "title": title, "columns": [{"label": c} for c in cols], "rows": rows, "total": len(rows)}


def test_merge_same_schema_combines_rows():
    from mia.api.legacy_view import _merge_same_schema_tables

    cols = ["Persona", "Departamento"]
    t1 = _make_table("Turnos 07/10/2026 — Restaurante", cols, [["Ana", "Restaurante"]] * 14)
    t2 = _make_table("Turnos 07/10/2026 — Cocina", cols, [["Bob", "Cocina"]] * 3)
    merged = _merge_same_schema_tables([t1, t2])
    assert len(merged) == 1
    assert merged[0]["total"] == 17
    assert merged[0]["title"] == "Turnos 07/10/2026"


def test_merge_strips_common_prefix_only():
    from mia.api.legacy_view import _merge_same_schema_tables

    cols = ["Persona"]
    t1 = _make_table("Turnos 07/10/2026 — Restaurante", cols, [["Ana"]])
    t2 = _make_table("Turnos 07/10/2026 — Cocina", cols, [["Bob"]])
    merged = _merge_same_schema_tables([t1, t2])
    assert merged[0]["title"] == "Turnos 07/10/2026"


def test_merge_does_not_merge_different_schemas():
    from mia.api.legacy_view import _merge_same_schema_tables

    t1 = _make_table("Tabla A", ["Persona", "Tipo"], [["Ana", "T"]])
    t2 = _make_table("Tabla B", ["Persona", "Puesto"], [["Bob", "P"]])
    result = _merge_same_schema_tables([t1, t2])
    assert len(result) == 2


def test_merge_single_table_unchanged():
    from mia.api.legacy_view import _merge_same_schema_tables

    t = _make_table("Solo", ["A"], [["x"]])
    assert _merge_same_schema_tables([t]) == [t]


def test_legacy_view_merges_two_dept_tables():
    from mia.api.legacy_view import legacy_view
    from mia.modules.rrhh.common import table

    p1 = table("Turnos 07/10/2026 — Restaurante", ["Persona", "Puesto", "Departamento", "Tipo", "Turno", "Área", "Comentario"],
                [["Ana", "CAMARERO", "Restaurante", "Trabajo", "08:00-16:00", None, None]] * 14)
    p2 = table("Turnos 07/10/2026 — Cocina", ["Persona", "Puesto", "Departamento", "Tipo", "Turno", "Área", "Comentario"],
                [["Bob", "FREGADOR", "Cocina", "Trabajo", "10:00-18:00", None, None]] * 3)

    data, _ = legacy_view([p1, p2])
    assert data["table"]["total"] == 17
    assert data["table"]["title"] == "Turnos 07/10/2026"
    assert "cards" not in data or not any(
        c.get("unit") == "registros" and c.get("value") == 3 for c in data.get("cards", [])
    )


# ── QueryAnalysis es frozen/hashable ─────────────────────────────────────────

def test_query_analysis_is_frozen():
    qa = classify_query("quien trabaja ahora")
    with pytest.raises((AttributeError, TypeError)):
        qa.presentation_intent = PresentationIntent.REPORT  # type: ignore[misc]
