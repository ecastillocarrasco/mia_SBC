"""Motor de comparativas homogéneas (Bloque II, sección 8). Cada comprobación es una función pura,
deliberadamente separada del cálculo de la comparación (``mia.analytics.comparison``): decide SI se
puede comparar, no CÓMO. Las pruebas usan ejemplos realistas, no datos inventados para que pase."""

from __future__ import annotations

from datetime import date

from mia.analytics.homogeneity import (
    check_denominator,
    check_granularity,
    check_period_pair,
    check_populations,
    check_units,
    has_blocker,
)
from mia.query.period import period_engine


def test_two_full_closed_months_are_comparable() -> None:
    today = date(2026, 10, 11)
    agosto = period_engine.resolve("agosto 2026", today=today)
    septiembre = period_engine.resolve("septiembre 2026", today=today)
    issues = check_period_pair(agosto, septiembre, today=today)
    assert not has_blocker(issues)


def test_current_partial_month_vs_a_closed_month_is_blocked() -> None:
    """Caso real del encargo (sección 8): «no comparar periodos parciales como si fueran completos»."""
    today = date(2026, 10, 11)  # octubre todavía no ha terminado
    octubre_en_curso = period_engine.resolve("este mes", today=today)
    septiembre_cerrado = period_engine.resolve("mes pasado", today=today)
    issues = check_period_pair(octubre_en_curso, septiembre_cerrado, today=today)
    assert has_blocker(issues)
    assert any("en curso" in i.message for i in issues)


def test_two_ongoing_periods_as_of_the_same_today_are_not_blocked_by_that_rule() -> None:
    """Si AMBOS periodos llegan hasta hoy (p. ej. «lo que llevamos de este año» en dos años distintos,
    cada uno evaluado con su propio «hoy» relativo), ninguno es "el parcial frente al completo"."""
    today = date(2026, 10, 11)
    ytd_2026 = period_engine.resolve("YTD", today=today)
    ytd_2026_again = period_engine.resolve("desde inicio de año", today=today)
    issues = check_period_pair(ytd_2026, ytd_2026_again, today=today)
    assert not any("en curso" in i.message for i in issues)


def test_wildly_different_period_lengths_are_flagged_as_a_warning_not_a_blocker() -> None:
    today = date(2026, 10, 11)
    una_semana = period_engine.resolve("semana pasada", today=today)
    un_trimestre = period_engine.resolve("Q2 2026", today=today)
    issues = check_period_pair(una_semana, un_trimestre, today=today)
    assert not has_blocker(issues)  # no es un periodo parcial vs completo, solo muy distinta duración
    assert any(i.severity == "data_quality" and "duraciones muy distintas" in i.message for i in issues)
    assert any(i.code == "PERIOD_DURATION_MISMATCH" for i in issues)


def test_similar_length_periods_are_not_flagged_for_duration() -> None:
    today = date(2026, 10, 11)
    agosto = period_engine.resolve("agosto 2026", today=today)
    septiembre = period_engine.resolve("septiembre 2026", today=today)
    issues = check_period_pair(agosto, septiembre, today=today)
    assert not any("duraciones muy distintas" in i.message for i in issues)


def test_empty_population_blocks_the_comparison() -> None:
    issues = check_populations(0, 12, label_a="Cocina", label_b="Recepción")
    assert has_blocker(issues)
    assert "Cocina" in issues[0].message


def test_non_empty_populations_are_not_blocked() -> None:
    assert check_populations(5, 12, label_a="Cocina", label_b="Recepción") == []


def test_zero_or_missing_denominator_blocks_percentage_calculation() -> None:
    assert check_denominator(0, context="coste del año anterior").severity == "blocker"
    assert check_denominator(None, context="coste del año anterior").severity == "blocker"
    assert check_denominator(1500.0, context="coste del año anterior") is None


def test_mismatched_units_block_the_comparison() -> None:
    issues = check_units("€", "días", label_a="Coste salarial", label_b="Absentismo")
    assert has_blocker(issues)
    assert issues[0].code == "UNIT_MISMATCH"


def test_matching_or_missing_units_are_not_blocked() -> None:
    assert check_units("€", "€", label_a="A", label_b="B") == []
    assert check_units("", "", label_a="A", label_b="B") == []


def test_mismatched_granularity_warns_but_does_not_block() -> None:
    issues = check_granularity("per_employee", "per_payslip", label_a="Edad", label_b="Líquido")
    assert not has_blocker(issues)
    assert issues[0].severity == "data_quality"
    assert issues[0].code == "GRANULARITY_MISMATCH"


def test_homogeneity_issue_to_dict_is_a_traceable_record() -> None:
    issues = check_populations(0, 5, label_a="Cocina", label_b="Pisos")
    record = issues[0].to_dict()
    assert record["severity"] == "blocker"
    assert record["code"] == "POPULATION_EMPTY"
    assert record["source"] == "mia.analytics.homogeneity"
    assert record["context"]["label_a"] == "Cocina"
