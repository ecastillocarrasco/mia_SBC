"""ReportPlanner (Bloque II, Fase B): de una petición en lenguaje natural a un plan validado contra el
catálogo semántico y los permisos reales del usuario — determinista, sin LLM (ver docstring de
planner.py). Las peticiones de prueba son variantes de los ejemplos literales de la sección 2 del
encargo del Bloque II, no frases inventadas a propósito para que el test pase."""

from __future__ import annotations

from datetime import date

from mia.auth import UserContext
from mia.reporting.planner import ReportPlanner

TODAY = date(2026, 10, 11)
ADMIN = UserContext("u1", "Admin", roles=frozenset({"mia.admin"}))
RESPONSABLE = UserContext("u2", "Responsable", roles=frozenset({"mia.responsable"}))  # sin nominas:importes


def test_plan_resolves_multiple_fields_dimension_and_metric() -> None:
    planner = ReportPlanner()
    plan = planner.plan(
        "Genera un informe de evolución de plantilla de los últimos tres años, desglosado por departamentos",
        user=ADMIN, today=TODAY,
    )
    assert plan.period is not None
    assert plan.period.start == date(2023, 10, 11)
    dim_names = [fd.name for fd in plan.dimensions]
    assert "department" in dim_names
    assert plan.compare is True  # "evolución" cuenta como señal de comparación


def test_plan_detects_requested_format() -> None:
    planner = ReportPlanner()
    plan = planner.plan("Prepara un PowerPoint ejecutivo sobre la evolución de Recursos Humanos", user=ADMIN)
    assert plan.requested_format == "pptx"

    plan_xlsx = planner.plan("Exporta a Excel todos los registros autorizados", user=ADMIN)
    assert plan_xlsx.requested_format == "xlsx"


def test_plan_denies_payroll_metric_without_permission_but_explains_why() -> None:
    """El campo denegado no desaparece en silencio: queda en el plan marcado como no concedido, con
    una advertencia explícita — así la capa que use el plan puede informar al usuario, no solo omitir
    el dato sin que nadie sepa por qué."""
    planner = ReportPlanner()
    plan = planner.plan("Compara los costes salariales de todos los departamentos entre 2024 y 2025", user=RESPONSABLE)
    salary_metrics = [m for m in plan.metrics if m.field.name == "coste_empresa"]
    assert salary_metrics, "debería haber reconocido el campo de coste salarial"
    assert salary_metrics[0].granted is False
    assert not any(m.field.name == "coste_empresa" for m in plan.granted_metrics)
    assert any("coste_empresa" in w for w in plan.warnings)


def test_plan_grants_payroll_metric_with_permission_and_flags_protected_route() -> None:
    planner = ReportPlanner()
    plan = planner.plan("¿Cuánto cobra de media el departamento de Cocina este año?", user=ADMIN, today=TODAY)
    liquido = next(m for m in plan.metrics if m.field.name == "liquido")
    assert liquido.granted is True
    assert liquido.requires_protected_route is True  # min_group=3 en el catálogo: debe ir por la ruta auditada


def test_plan_non_payroll_metric_never_requires_protected_route() -> None:
    planner = ReportPlanner()
    plan = planner.plan("¿Cuál es la edad media de la plantilla?", user=RESPONSABLE, today=TODAY)
    age = next(m for m in plan.metrics if m.field.name == "age")
    assert age.granted is True
    assert age.requires_protected_route is False


def test_plan_with_unrecognized_text_is_empty_and_warns() -> None:
    planner = ReportPlanner()
    plan = planner.plan("hola, buenos días", user=ADMIN, today=TODAY)
    assert plan.is_empty is True
    assert plan.warnings


def test_plan_without_a_recognizable_period_still_resolves_fields_but_warns() -> None:
    planner = ReportPlanner()
    plan = planner.plan("¿Cuál es la edad media de la plantilla?", user=ADMIN)
    assert plan.period is None
    assert any("periodo" in w.lower() for w in plan.warnings)
    assert not plan.is_empty  # el campo "age" sí se reconoció


def test_plan_absenteeism_report_example_from_the_brief() -> None:
    """Ejemplo casi literal de la sección 2: «informe completo sobre turnos, vacaciones, ausencias y
    absentismo»."""
    planner = ReportPlanner()
    plan = planner.plan(
        "Genera un informe completo sobre turnos, vacaciones, ausencias y absentismo", user=ADMIN, today=TODAY
    )
    names = {m.field.name for m in plan.metrics} | {fd.name for fd in plan.dimensions}
    assert "absence_days" in names or "absence_rate" in names
    assert "vacation_balance" in names or "vacation_days_taken" in names
