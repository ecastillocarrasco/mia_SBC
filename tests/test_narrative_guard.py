"""Requisito 7 de la ronda de validación del usuario: las conclusiones narrativas deben coincidir con
las cifras del backend; una discrepancia debe bloquearse antes de publicarse — nunca corregirse en
silencio inventando qué quiso decir el LLM, y nunca confundir "no verificable" con "verificado"."""

from __future__ import annotations

from mia.modules.rrhh.informes.document import narrative_statement
from mia.reporting.narrative_guard import enforce_narrative_integrity, verify_narrative_block, verify_statement

BACKEND = {"total_staff": 120.0, "absence_rate": 4.2, "total_cost": 0.0}


def test_matching_fact_is_not_flagged() -> None:
    stmt = narrative_statement("fact", "La plantilla es de 120 personas.", evidence={"metric": "total_staff", "value": 120.0})
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_rounding_within_tolerance_is_not_flagged() -> None:
    """119,5 frente a 120,0 es un 0,42% de diferencia — redondeo de presentación, no un error real."""
    stmt = narrative_statement("fact", "La plantilla es de unas 119,5 personas.", evidence={"metric": "total_staff", "value": 119.5})
    assert verify_statement(stmt, backend_values=BACKEND) is None


def test_mismatched_fact_is_flagged_as_a_real_discrepancy() -> None:
    stmt = narrative_statement("fact", "La plantilla creció a 200 personas.", evidence={"metric": "total_staff", "value": 200.0})
    discrepancy = verify_statement(stmt, backend_values=BACKEND)
    assert discrepancy is not None
    assert discrepancy.metric == "total_staff"
    assert discrepancy.claimed_value == 200.0
    assert discrepancy.backend_value == 120.0


def test_zero_backend_value_with_nonzero_claim_is_flagged() -> None:
    stmt = narrative_statement("fact", "El coste total fue de 500 €.", evidence={"metric": "total_cost", "value": 500.0})
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
        narrative_statement("fact", "La plantilla es de 120 personas.", evidence={"metric": "total_staff", "value": 120.0}),
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
