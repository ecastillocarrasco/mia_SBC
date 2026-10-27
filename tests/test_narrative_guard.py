"""Requisito 7 de la ronda de validación del usuario: las conclusiones narrativas deben coincidir con
las cifras del backend; una discrepancia debe bloquearse antes de publicarse — nunca corregirse en
silencio inventando qué quiso decir el LLM, y nunca confundir "no verificable" con "verificado"."""

from __future__ import annotations

import pytest

from mia.modules.rrhh.informes.document import narrative_statement
from mia.reporting.narrative_generation import _parse_statements
from mia.reporting.narrative_guard import (
    enforce_narrative_integrity,
    enforce_narrative_period_coherence,
    verify_narrative_block,
    verify_statement,
    verify_statement_period,
)

BACKEND = {"total_staff": 120.0, "absence_rate": 4.2, "total_cost": 0.0}


def test_matching_fact_is_not_flagged() -> None:
    stmt = narrative_statement(
        "fact", "La plantilla es de 120 personas.", evidence={"metric": "total_staff", "value": 120.0}
    )
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_rounding_within_tolerance_is_not_flagged() -> None:
    """119,5 frente a 120,0 es un 0,42% de diferencia — redondeo de presentación, no un error real."""
    stmt = narrative_statement(
        "fact", "La plantilla es de unas 119,5 personas.", evidence={"metric": "total_staff", "value": 119.5}
    )
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_mismatched_fact_is_flagged_as_a_real_discrepancy() -> None:
    stmt = narrative_statement(
        "fact", "La plantilla creció a 200 personas.", evidence={"metric": "total_staff", "value": 200.0}
    )
    discrepancy = verify_statement(stmt, backend_values=BACKEND)
    assert discrepancy is not None
    assert discrepancy.metric == "total_staff"
    assert discrepancy.claimed_value == 200.0
    assert discrepancy.backend_value == 120.0


def test_zero_backend_value_with_nonzero_claim_is_flagged() -> None:
    stmt = narrative_statement(
        "fact", "El coste total fue de 500 €.", evidence={"metric": "total_cost", "value": 500.0}
    )
    assert verify_statement(stmt, backend_values=BACKEND) is not None


def test_non_fact_statements_are_never_verified() -> None:
    """Una hipótesis o recomendación puede citar cualquier cifra sin que esto la "verifique" — solo los
    hechos declarados como tales se comprueban contra el backend."""
    stmt = narrative_statement("hypothesis", "Quizá la plantilla llegue a 500 personas el año que viene.")
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_fact_citing_an_unknown_metric_is_not_flagged() -> None:
    """No se puede refutar (ni confirmar) una afirmación que cita una métrica que el backend no
    conoce: se deja pasar sin marcar, no se inventa un "backend_value" para ella."""
    stmt = narrative_statement("fact", "El NPS fue de 85.", evidence={"metric": "nps_score", "value": 85.0})
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_verify_narrative_block_collects_only_the_real_discrepancies() -> None:
    statements = [
        narrative_statement(
            "fact", "La plantilla es de 120 personas.", evidence={"metric": "total_staff", "value": 120.0}
        ),
        narrative_statement("fact", "El absentismo fue del 9%.", evidence={"metric": "absence_rate", "value": 9.0}),
        narrative_statement("recommendation", "Conviene revisar la cobertura de Cocina."),
    ]
    discrepancies = verify_narrative_block(statements, backend_values=BACKEND)
    assert len(discrepancies) == 1
    assert discrepancies[0].metric == "absence_rate"


def test_enforce_narrative_integrity_blocks_the_discrepant_text_with_the_real_value_visible() -> None:
    statements = [
        narrative_statement("fact", "El absentismo fue del 9%.", evidence={"metric": "absence_rate", "value": 9.0}),
        narrative_statement("recommendation", "Conviene revisar la cobertura de Cocina."),
    ]
    fixed = enforce_narrative_integrity(statements, backend_values=BACKEND)
    assert "BLOQUEADA" in fixed[0]["text"]
    assert "4.2" in fixed[0]["text"]  # la cifra real queda visible, no oculta
    assert fixed[0]["evidence"]["blocked"] is True
    assert fixed[1]["text"] == "Conviene revisar la cobertura de Cocina."  # intacta: no era una discrepancia


# ──────────────────────────────────── punto 3 de la ronda de validación (Fase F): casos explícitos pedidos


def test_an_incorrect_amount_is_blocked() -> None:
    stmt = narrative_statement(
        "fact", "El coste total ascendió a 9.999 €.", evidence={"metric": "total_cost", "value": 9999.0}
    )
    assert verify_statement(stmt, backend_values=BACKEND) is not None


def test_an_incorrect_percentage_is_blocked() -> None:
    """Caso explícitamente pedido: "porcentajes equivocados" — una tasa de absentismo citada mal."""
    stmt = narrative_statement("fact", "El absentismo fue del 15%.", evidence={"metric": "absence_rate", "value": 15.0})
    discrepancy = verify_statement(stmt, backend_values=BACKEND)
    assert discrepancy is not None
    assert discrepancy.backend_value == 4.2


def test_an_unsupported_fact_claim_is_rejected_before_it_ever_reaches_the_guard() -> None:
    """Caso explícitamente pedido: "conclusiones no respaldadas" — una afirmación de tipo 'fact' sin
    evidencia ni se puede construir (``narrative_statement`` la rechaza en el origen), y si el LLM la
    devuelve de todos modos en el JSON crudo, ``_parse_statements`` la descarta en vez de dejarla pasar
    sin respaldo."""
    with pytest.raises(ValueError, match="evidencia"):
        narrative_statement("fact", "El equipo está muy motivado.")

    raw = (
        '{"statements": ['
        '{"kind": "fact", "text": "El equipo está muy motivado."},'
        '{"kind": "interpretation", "text": "El ambiente parece positivo."}'
        "]}"
    )
    parsed = _parse_statements(raw)
    assert parsed is not None
    assert len(parsed) == 1  # la afirmación "fact" sin evidencia se descarta, no se publica sin respaldo
    assert parsed[0]["kind"] == "interpretation"


def test_narrative_guard_never_parses_free_text_prose_for_a_period() -> None:
    """Límite de diseño deliberado (no un hueco sin corregir): ``verify_statement`` comprueba el VALOR
    NUMÉRICO contra el backend, pero NUNCA analiza con expresiones regulares el periodo que la PROSA
    libre describe — el riesgo de falso positivo sobre comparativas legítimas entre varios periodos es
    real y no está validado. La coherencia temporal real se resuelve con un campo ESTRUCTURADO
    (``evidence.period``, ver ``verify_statement_period``/``enforce_narrative_period_coherence`` más
    abajo), nunca con un analizador de texto libre."""
    stmt = narrative_statement(
        "fact",
        "En julio el absentismo fue del 4,2%.",  # la prosa dice julio; el dato real es de agosto
        evidence={"metric": "absence_rate", "value": 4.2},  # sin 'period' estructurado declarado
    )
    assert verify_statement(stmt, backend_values=BACKEND) is None  # el NÚMERO coincide
    # Y, al no haber declarado NINGÚN periodo estructurado, tampoco hay nada que verificar aquí: "no
    # verificable" nunca se trata como "incorrecto", pero tampoco como "correcto".
    assert verify_statement_period(stmt, expected_period="Agosto 2026") is None


def test_an_incorrect_period_with_a_correct_amount_is_blocked_via_structured_evidence() -> None:
    """Caso explícitamente pedido: "periodos incorrectos con cifras correctas", resuelto con
    afirmaciones estructuradas (métrica + periodo + valor en la evidencia), nunca con un analizador de
    texto libre. El VALOR es correcto, pero el PERIODO declarado no coincide con el real del informe."""
    stmt = narrative_statement(
        "fact",
        "En julio el absentismo fue del 4,2%.",
        evidence={"metric": "absence_rate", "value": 4.2, "period": "Julio 2026"},
    )
    discrepancy = verify_statement_period(stmt, expected_period="Agosto 2026")
    assert discrepancy is not None
    assert discrepancy.claimed_period == "Julio 2026"
    assert discrepancy.expected_period == "Agosto 2026"
    # El valor numérico, aislado, seguiría pasando — la incoherencia es de periodo, no de cifra.
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_a_correct_period_declared_structurally_is_not_flagged() -> None:
    stmt = narrative_statement(
        "fact",
        "En agosto el absentismo fue del 4,2%.",
        evidence={"metric": "absence_rate", "value": 4.2, "period": "Agosto 2026"},
    )
    assert verify_statement_period(stmt, expected_period="Agosto 2026") is None
    assert verify_statement_period(stmt, expected_period="agosto 2026") is None  # insensible a mayúsculas/tildes


def test_enforce_narrative_period_coherence_blocks_with_both_periods_visible() -> None:
    statements = [
        narrative_statement(
            "fact",
            "En julio el absentismo fue del 4,2%.",
            evidence={"metric": "absence_rate", "value": 4.2, "period": "Julio 2026"},
        ),
        narrative_statement("recommendation", "Conviene revisar la cobertura de Cocina."),
    ]
    fixed = enforce_narrative_period_coherence(statements, expected_period="Agosto 2026")
    assert "BLOQUEADA" in fixed[0]["text"]
    assert "Julio 2026" in fixed[0]["text"] and "Agosto 2026" in fixed[0]["text"]
    assert fixed[0]["evidence"]["period_blocked"] is True
    assert fixed[1]["text"] == "Conviene revisar la cobertura de Cocina."  # intacta


def test_enforce_narrative_period_coherence_is_a_no_op_without_an_expected_period() -> None:
    """Sin un periodo real con el que comparar (p. ej. un resumen sin 'periodo_interpretado'), no se
    bloquea nada — "no verificable" nunca se trata como "incorrecto"."""
    statements = [
        narrative_statement(
            "fact",
            "En julio el absentismo fue del 4,2%.",
            evidence={"metric": "absence_rate", "value": 4.2, "period": "Julio 2026"},
        ),
    ]
    assert enforce_narrative_period_coherence(statements, expected_period=None) == statements
