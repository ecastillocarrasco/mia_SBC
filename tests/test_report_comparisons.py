"""Comparativas sintéticas con diferencias, protección de grupos y ausencia de datos."""
import pytest
from mia.reporting.comparisons import explicit_month_comparison, merge_payroll_comparison


def fixture_summary(period, departments):
    return {"concepto_economico": "Coste empresa", "poblacion": "activos e inactivos",
            "meses_analizados": [period], "meses_con_datos": [period], "meses_sin_datos": None,
            "por_departamento": departments, "advertencias": None}


def test_compare_months_with_de_in_any_order():
    assert explicit_month_comparison('compara agosto de 2026 con agosto de 2025') == ('2025-08', '2026-08')
    assert explicit_month_comparison('compara agosto de 2026') is None
    assert explicit_month_comparison('compara agosto y 2025') is None


def test_protect_hidden_departments_and_matched_population():
    old = fixture_summary('2025-08', {"Sistemas": {"total": 100, "personas_con_nomina": 4},
                                      "Protegido": {"personas_con_nomina": 2}})
    new = fixture_summary('2026-08', {"Sistemas": {"total": 125, "personas_con_nomina": 4},
                                      "Protegido": {"total": 75, "personas_con_nomina": 3}})
    p, summary = merge_payroll_comparison(old, new, ('2025-08', '2026-08'))
    assert p['rows'][0][:5] == ['Sistemas', 100.0, 125.0, 25.0, 25.0]
    assert len(p['rows']) == 2
    assert summary['total_comparable_actual'] == 125
    assert summary['total_comparable_anterior'] == 100
    assert summary['departamentos_comparables'] == 1
    assert any('NOM-005' in a for a in summary['advertencias'])
    assert len(p['charts'][0]['series']) == 2


def test_mismatched_period_rejected():
    old = fixture_summary('2025-07', {"Sistemas": {"total": 100}})
    new = fixture_summary('2026-08', {"Sistemas": {"total": 125}})
    with pytest.raises(ValueError):
        merge_payroll_comparison(old, new, ('2025-08', '2026-08'))


def test_no_total_from_protected_groups():
    old = fixture_summary('2025-08', {"Protegido": {"personas_con_nomina": 2}})
    new = fixture_summary('2026-08', {"Protegido": {"total": 120, "personas_con_nomina": 3}})
    with pytest.raises(ValueError, match='No hay departamentos'):
        merge_payroll_comparison(old, new, ('2025-08', '2026-08'))

@pytest.mark.parametrize('sentence', [
    'Compara el coste de nominas en agosto de 2025 y 2026',
    'Genera un PDF de agosto 2025/2026 por departamento',
    'agosto de los años 2025 y 2026',
    'agosto 2026 frente a 2025',
    '2025 vs 2026 en agosto',
    'comparativa agosto del 2026 y del 2025',
])
def test_comparison_with_shared_month_and_two_years(sentence):
    assert explicit_month_comparison(sentence) == ('2025-08', '2026-08')


@pytest.mark.parametrize('sentence', [
    'agosto de 2026',
    'compara 2025 y 2026',
    'agosto de 2025 con septiembre de 2026 y octubre 2026',
    'agosto 2025 y octubre 2026 y mayo',
    'agosto 2025 y octubre de 2026',
])
def test_comparison_rejects_incomplete_or_ambiguous_periods(sentence):
    # Two complete but different months ARE explicit and can be compared, but
    # two years alone and contradictory multi-month requests must not be guessed.
    if sentence == 'agosto 2025 y octubre de 2026':
        assert explicit_month_comparison(sentence) == ('2025-08', '2026-10')
    else:
        assert explicit_month_comparison(sentence) is None
