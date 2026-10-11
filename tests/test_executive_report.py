"""Caracterización de ``build_executive_report`` (informe ejecutivo de RRHH) — regresión que NO
existía (ver auditoría de la Fase A del Bloque II: "executive report builder has no dedicated
render-level test found"). Captura el comportamiento real actual con datos sintéticos conocidos, sirve
de base para cualquier cambio posterior (p. ej. conectarlo a ``mia.analytics`` en la Fase C) sin que el
resultado numérico cambie en silencio.

Los valores esperados se obtuvieron ejecutando la función real contra la siembra de
``tests/hr_seed.py`` (TODAY = 2026-08-05) y verificándolos a mano contra esos datos (ver el trazado en
el propio test, no son cifras arbitrarias): 3 empleados activos (Ana Ruiz Sanz, Ana Gómez, Eva Sol —
Luis Gil está inactivo y se excluye), un periodo de vacaciones (Ana Ruiz, 01-07 ago, 5 días dentro de
agosto) y uno de baja (Eva Sol, 05-06 ago, 2 días).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from mia.data import ShiftDay
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.informes.executive import build_executive_report
from tests.dbutil import fresh_database
from tests.hr_seed import seed

TODAY = date(2026, 8, 5)
_WEEKDAYS = "LMXJVSD"


async def _report(tmp_path: Path, dept_key: str | None = None, dept_name: str | None = None):
    db = await fresh_database(tmp_path, "executive_report.db")
    await seed(db)
    deps = Deps(db=db)
    return await build_executive_report(deps, date(2026, 8, 1), date(2026, 8, 31), TODAY, dept_key, dept_name)


def _block(doc, title: str):
    return next(b for b in doc.blocks if b.title == title)


async def test_executive_report_kpis_match_the_seeded_data_exactly(tmp_path: Path) -> None:
    doc = await _report(tmp_path)
    kpis = _block(doc, "Resumen ejecutivo").data
    assert kpis["Plantilla activa"] == 3  # Luis Gil (inactivo) no cuenta
    assert kpis["Trabajando hoy"] == 1  # Ana Gómez
    assert kpis["Ausentes hoy"] == 2  # Ana Ruiz (vacaciones) + Eva Sol (baja)
    assert kpis["Descansando hoy"] == 0
    assert kpis["Sin turno hoy"] == 0
    assert kpis["Bajas IT en periodo"] == 1
    assert kpis["Personas con ausencia"] == 2
    assert kpis["Días de absentismo"] == 7  # 5 (vacaciones) + 2 (baja)
    assert kpis["Duración media ausencia"] == "3.5 días"
    assert kpis["Saldo medio vacaciones"] == "1.8 días"  # media de -2.5 y 6
    assert kpis["Saldos negativos"] == 1
    assert kpis["Sol. vacaciones pendientes"] == 1
    assert kpis["Nóminas 2026-07"] == 0  # hr_seed no siembra ninguna nómina
    assert kpis["ETT horas en periodo"] == 0.0
    assert kpis["ETT importe en periodo"] == "0.00 €"


async def test_executive_report_department_and_position_breakdowns(tmp_path: Path) -> None:
    """El orden entre departamentos/puestos empatados a 1 persona no está garantizado por SQL — se
    compara como conjunto, no como lista exacta, para no acoplar el test a un orden no determinista."""
    doc = await _report(tmp_path)
    by_dept = _block(doc, "Plantilla por departamento").data
    assert by_dept["columns"] == ["Departamento", "Personas"]
    assert {tuple(r) for r in by_dept["rows"]} == {("Spa", 1), ("Pisos", 1), ("Cocina", 1)}

    by_position = _block(doc, "Distribución por puesto").data
    assert by_position["columns"] == ["Puesto", "Personas"]
    assert {tuple(r) for r in by_position["rows"]} == {("Terapeuta", 1), ("Cocinera", 1), ("Camarera de pisos", 1)}


async def test_executive_report_absence_breakdown_by_kind(tmp_path: Path) -> None:
    doc = await _report(tmp_path)
    absences = _block(doc, "Absentismo · 01/08/2026 – 31/08/2026").data
    rows_by_kind = {r[0]: r for r in absences["rows"]}
    # [tipo, periodos, personas, dias_acumulados, duracion_media, periodo_mas_largo]
    assert rows_by_kind["Baja/IT"] == ["Baja/IT", 1, 1, 2, 2.0, 2]
    assert rows_by_kind["Vacaciones"] == ["Vacaciones", 1, 1, 5, 5.0, 5]


async def test_executive_report_monthly_absence_trend(tmp_path: Path) -> None:
    doc = await _report(tmp_path)
    trend = _block(doc, "Tendencia mensual de absentismo").data
    assert trend["rows"] == [["ago", 7]]  # las dos ausencias empiezan en agosto: 5 + 2


async def test_executive_report_vacation_balance_distribution(tmp_path: Path) -> None:
    doc = await _report(tmp_path)
    dist = _block(doc, "Distribución de saldos de vacaciones · 2026").data
    assert {tuple(r) for r in dist["rows"]} == {
        ("0 a 9 días", 1),  # Ana Gómez: 6
        ("Saldo negativo", 1),  # Ana Ruiz Sanz: -2.5
        ("Sin saldo registrado", 1),  # Eva Sol: sin VacationBalance sembrado
    }


async def test_executive_report_monthly_trend_includes_a_second_month_with_a_verifiable_finding(
    tmp_path: Path,
) -> None:
    """Ajuste de Fase C: con datos de un solo mes, ``InsightEngine.from_time_series`` no puede detectar
    ninguna tendencia (exige ≥2 puntos) — por eso la siembra estándar de ``hr_seed`` nunca ejercita este
    bloque. Se añade aquí, solo para esta prueba, un segundo mes de ausencia (Ana Gómez, vacaciones en
    julio) para poder verificar de verdad el hallazgo generado, con el mismo motor determinista que ya
    usan otros dominios (``mia.analytics.insights.InsightEngine``) — no una afirmación sin comprobar."""
    db = await fresh_database(tmp_path, "executive_report_trend.db")
    await seed(db)
    async with db.session() as s:
        rows = []
        for i, day in enumerate(date(2026, 7, 6) + timedelta(days=d) for d in range(5)):
            iso = day.isocalendar()
            rows.append(
                ShiftDay(
                    sp_item_id=900 + i,
                    day=day,
                    person_key="pk-anag",
                    employee_name="Ana Gómez",
                    department="Cocina",
                    department_key="cocina",
                    iso_year=iso.year,
                    iso_week=iso.week,
                    weekday=_WEEKDAYS[day.weekday()],
                    raw_value="VACACIONES",
                    kind="Vacaciones",
                )
            )
        s.add_all(rows)

    deps = Deps(db=db)
    doc = await build_executive_report(deps, date(2026, 7, 1), date(2026, 8, 31), TODAY, None, None)

    trend = _block(doc, "Tendencia mensual de absentismo").data
    assert trend["rows"] == [["jul", 5], ["ago", 7]]  # 7 = 5 (Ana Ruiz) + 2 (Eva Sol), como antes

    findings = _block(doc, "Hallazgos · Absentismo").data
    assert findings  # el bloque solo se añade si from_time_series() devolvió algo verificable
    joined = " ".join(findings.values())
    assert "40.0%" in joined  # (7-5)/5*100, calculado por InsightEngine, no escrito a mano aquí


async def test_executive_report_department_filter_narrows_everything(tmp_path: Path) -> None:
    """Filtrar por departamento (Cocina) debe excluir a las personas de otros departamentos de TODOS
    los bloques, no solo del de plantilla."""
    doc = await _report(tmp_path, dept_key="cocina", dept_name="Cocina")
    kpis = _block(doc, "Resumen ejecutivo").data
    assert kpis["Plantilla activa"] == 1  # solo Ana Gómez
    assert kpis["Ausentes hoy"] == 0  # Ana Gómez trabaja hoy
    assert kpis["Personas con ausencia"] == 0  # ninguna ausencia en Cocina en agosto
    # El bloque de ETT es explícitamente global (sección "sólo global, no filtrada por departamento")
    assert not any(b.title.startswith("Trabajo temporal") for b in doc.blocks)
