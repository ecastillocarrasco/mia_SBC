"""Consulta cruzada: criterios de varios dominios sobre las mismas personas."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry
from mia.data import Employee, Payslip, ShiftDay, SignedDocument, Vacation, VacationBalance
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, _shift

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
NOW = datetime(2026, 8, 5, 10, tzinfo=ZoneInfo("Europe/Madrid"))
TODAY = NOW.date()


def _person(  # noqa: PLR0917
    sp_id: int, name: str, dept: str, position: str, mail: str, key: str, born: date, **kw: Any
) -> Employee:
    e = _emp(sp_id, name, dept, email=mail, person_key=key, position=position, **kw)
    e.birth_date = born
    return e


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "cruz.db")
    tomorrow = TODAY + timedelta(days=1)
    async with db.session() as s:
        s.add_all(
            [
                _person(1, "Ana Ruiz", "Cocina", "Cocinera", "ana@x", "pk-1", date(1990, 8, 20)),
                _person(2, "Beto Gil", "Cocina", "Ayudante de cocina", "beto@x", "pk-2", date(1985, 3, 2)),
                _person(3, "Cris Paz", "Pisos", "Camarera de pisos", "cris@x", "pk-3", date(1970, 8, 9)),
                _person(4, "Dani Sol", "Pisos", "Camarera de pisos", "dani@x", "pk-4", date(2000, 1, 5)),
                _person(5, "Exempleado Uno", "Cocina", "Cocinero", "ex@x", "pk-5", date(1980, 1, 1), active=False),
                # turnos
                _shift(1, "pk-1", "Ana Ruiz", "Cocina", TODAY, "Vacaciones", "Vacaciones"),
                _shift(2, "pk-2", "Beto Gil", "Cocina", TODAY, "Trabajo", "14:00-22:00"),
                _shift(3, "pk-3", "Cris Paz", "Pisos", TODAY, "Baja/IT", "Baja"),
                _night(_shift(4, "pk-4", "Dani Sol", "Pisos", tomorrow, "Trabajo", "23:00-07:00")),
                _shift(5, "pk-5", "Exempleado Uno", "Cocina", TODAY, "Vacaciones", "Vacaciones"),
                # vacaciones y saldos
                Vacation(
                    sp_id=1,
                    employee_email="ana@x",
                    employee_name="Ana Ruiz",
                    department="Cocina",
                    department_key="cocina",
                    status="Aceptada",
                    request_type="Vacaciones",
                    start_date=TODAY,
                    end_date=tomorrow,
                    total_days=2,
                ),
                Vacation(
                    sp_id=2,
                    employee_email="ex@x",
                    employee_name="Exempleado Uno",
                    department="Cocina",
                    department_key="cocina",
                    status="Aceptada",
                    request_type="Vacaciones",
                    start_date=TODAY,
                    end_date=tomorrow,
                    total_days=2,
                ),
                VacationBalance(
                    sp_id=1,
                    employee_email="ana@x",
                    employee_name="Ana Ruiz",
                    department="Cocina",
                    year=TODAY.year,
                    current_balance=-3.0,
                    total_balance=24.0,
                ),
                VacationBalance(
                    sp_id=2,
                    employee_email="beto@x",
                    employee_name="Beto Gil",
                    department="Cocina",
                    year=TODAY.year,
                    current_balance=10.0,
                    total_balance=24.0,
                ),
                # nóminas y documentos
                Payslip(sp_id=1, person_key="pk-1", year=2026, month=7, period="2026-07", special=False, read=False),
                Payslip(sp_id=2, person_key="pk-2", year=2026, month=7, period="2026-07", special=False, read=True),
                Payslip(sp_id=3, person_key="pk-2", year=2026, month=6, period="2026-06", special=False, read=True),
                SignedDocument(sp_id=1, person_key="pk-1", doc_type="Contrato", file_name="c.pdf"),
            ]
        )
    yield build_registry(db)
    await db.dispose()


def _night(shift: ShiftDay) -> ShiftDay:
    shift.start_time, shift.end_time = "23:00", "07:00"
    return shift


async def q(registry: ToolRegistry, **args: Any) -> Any:
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    return (await registry.execute(ToolCall("c", "consulta_cruzada", json.dumps(args, default=str)), ctx)).result


def names(result: Any) -> set[str]:
    return {r["persona"] for r in result.summary["detalle"]}


async def test_department_and_vacation_and_negative_balance(registry: ToolRegistry) -> None:
    result = await q(
        registry,
        departamento="Cocina",
        condiciones=[{"que": "de_vacaciones"}, {"que": "saldo_menor_que", "valor": 0}],
        campos=["puesto", "saldo_vacaciones"],
    )
    assert names(result) == {"Ana Ruiz"}  # el exempleado también está de vacaciones pero no es plantilla activa
    assert result.summary["detalle"][0]["saldo_vacaciones"].startswith("-3")
    assert result.summary["poblacion"].startswith("plantilla activa")


async def test_inactive_only_when_explicitly_requested(registry: ToolRegistry) -> None:
    result = await q(registry, departamento="Cocina", incluir_inactivos=True, condiciones=[{"que": "de_vacaciones"}])
    assert names(result) == {"Ana Ruiz", "Exempleado Uno"}


async def test_shift_band_and_position_filter(registry: ToolRegistry) -> None:
    result = await q(
        registry,
        puesto="camarera",
        desde=str(TODAY + timedelta(days=1)),
        condiciones=[{"que": "trabaja", "valor": "noche"}],
    )
    assert names(result) == {"Dani Sol"}


async def test_negation_and_sick_leave(registry: ToolRegistry) -> None:
    sick = await q(registry, condiciones=[{"que": "de_baja"}])
    assert names(sick) == {"Cris Paz"}
    not_sick = await q(registry, departamento="Pisos", condiciones=[{"que": "de_baja", "negar": True}])
    assert names(not_sick) == {"Dani Sol"}


async def test_count_and_group_by(registry: ToolRegistry) -> None:
    count = await q(registry, operacion="contar", condiciones=[{"que": "con_ausencia"}])
    assert count.summary["total"] == 2 and "detalle" not in count.summary
    grouped = await q(registry, operacion="agrupar", agrupar_por="puesto")
    assert grouped.summary["grupos"]["Camarera de pisos"] == 2


async def test_birthdays_documents_and_payslips(registry: ToolRegistry) -> None:
    birthdays = await q(registry, condiciones=[{"que": "cumple_anios_en", "valor": 8}], campos=["cumpleanos"])
    assert {r["persona"]: r["cumpleanos"] for r in birthdays.summary["detalle"]} == {
        "Ana Ruiz": "20/08",
        "Cris Paz": "09/08",
    }
    assert names(await q(registry, condiciones=[{"que": "sin_documento", "valor": "contrato"}])) == {
        "Beto Gil",
        "Cris Paz",
        "Dani Sol",
    }
    assert names(await q(registry, condiciones=[{"que": "nominas_sin_leer"}])) == {"Ana Ruiz"}
    assert names(
        await q(registry, departamento="Cocina", condiciones=[{"que": "sin_nomina_del_periodo", "valor": "2026-06"}])
    ) == {"Ana Ruiz"}


async def test_follow_up_over_the_previous_result(registry: ToolRegistry) -> None:
    first = await q(registry, departamento="Cocina")
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state=dict(first.state_updates))
    second = (
        await registry.execute(
            ToolCall(
                "c",
                "consulta_cruzada",
                json.dumps({"sobre_resultado_anterior": True, "condiciones": [{"que": "saldo_mayor_que", "valor": 5}]}),
            ),
            ctx,
        )
    ).result
    assert names(second) == {"Beto Gil"}


async def test_department_360(registry: ToolRegistry) -> None:
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    result = (
        await registry.execute(ToolCall("c", "ficha_departamento", json.dumps({"departamento": "cocina"})), ctx)
    ).result
    s = result.summary
    assert s["departamento"] == "Cocina" and s["plantilla_activa"] == 2  # el exempleado no cuenta
    assert s["hoy"]["vacaciones"] == 1 and s["hoy"]["trabajando"] == 1
    assert s["vacaciones"]["con_saldo_negativo"] == 1 and s["personas_con_nominas_sin_leer"] == 1


async def _candidate_registry(tmp_path: Path) -> tuple[ToolRegistry, Any]:
    from mia.data import Candidate  # noqa: PLC0415

    database = await fresh_database(tmp_path, "cand.db")
    async with database.session() as s:
        s.add_all(
            [
                _person(1, "Ana Ruiz", "Cocina", "Cocinera", "ana@x", "pk-1", date(1990, 1, 1)),
                _person(2, "Ex Uno", "Cocina", "Cocinero", "ex@x", "pk-2", date(1980, 1, 1), active=False),
                Candidate(
                    sp_id=1, name="Ana Ruiz", name_key="ana ruiz", email="ana@x", department="Sala", status="Nuevo"
                ),
                Candidate(
                    sp_id=2, name="Ex Uno", name_key="ex uno", email="ex@x", department="Cocina", status="Pendiente"
                ),
                Candidate(sp_id=3, name="Otra Persona", name_key="otra persona", email="o@x", department="Cocina"),
            ]
        )
    return build_registry(database), database


async def test_candidate_cross_with_staff(tmp_path: Path) -> None:
    registry, database = await _candidate_registry(tmp_path)
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    result = (await registry.execute(ToolCall("c", "candidatos_y_plantilla", "{}"), ctx)).result
    await database.dispose()
    assert result.summary["empleados_actuales"] == 1 and result.summary["antiguos_empleados"] == 1
    assert {r["persona"] for r in result.summary["coincidencias"]} == {"Ana Ruiz", "Ex Uno"}


async def test_shift_mates_and_hours_of_one_person(tmp_path: Path) -> None:
    from mia.data import CalendarShift  # noqa: PLC0415

    db = await fresh_database(tmp_path, "mates.db")
    async with db.session() as s:
        s.add_all(
            [
                _person(1, "Ana Ruiz", "Cocina", "Cocinera", "ana@x", "pk-1", date(1990, 1, 1)),
                _person(2, "Beto Gil", "Cocina", "Cocinero", "beto@x", "pk-2", date(1990, 1, 1)),
                _person(3, "Cris Paz", "Cocina", "Cocinera", "cris@x", "pk-3", date(1990, 1, 1)),
                _shift(1, "pk-1", "Ana Ruiz", "Cocina", TODAY, "Trabajo", "7:00-15:00"),
                _shift(2, "pk-2", "Beto Gil", "Cocina", TODAY, "Trabajo", "7:00-15:00"),
                _night(_shift(3, "pk-3", "Cris Paz", "Cocina", TODAY, "Trabajo", "23:00-07:00")),
                CalendarShift(
                    sp_id=1,
                    department="Cocina",
                    year=2026,
                    department_key="cocina",
                    employee_name="Ana Ruiz",
                    employee_name_key="ana ruiz",
                    day=TODAY,
                    hours_total=8,
                    kind="work",
                    split_shift=False,
                ),
                CalendarShift(
                    sp_id=2,
                    department="Cocina",
                    year=2026,
                    department_key="cocina",
                    employee_name="Beto Gil",
                    employee_name_key="beto gil",
                    day=TODAY,
                    hours_total=6,
                    kind="work",
                    split_shift=False,
                ),
            ]
        )
    registry = build_registry(db)
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    mates = (
        await registry.execute(ToolCall("c", "companeros_de_turno", json.dumps({"nombre": "Ana Ruiz"})), ctx)
    ).result
    assert [m["persona"] for m in mates.summary["companeros"]] == ["Beto Gil"]  # Cris trabaja de noche: no coincide
    assert mates.summary["companeros"][0]["horas_coincidencia"] == 8.0
    hours = (
        await registry.execute(
            ToolCall(
                "c",
                "metricas_turnos",
                json.dumps({"departamento": "Cocina", "empleado": "beto", "desde": str(TODAY), "hasta": str(TODAY)}),
            ),
            ctx,
        )
    ).result
    await db.dispose()
    assert hours.summary["horas_totales"] == 6.0 and hours.summary["jornadas_trabajadas"] == 1


async def test_funnel_explains_where_the_result_is_lost(registry: ToolRegistry) -> None:
    result = await q(
        registry, departamento="Cocina", condiciones=[{"que": "de_vacaciones"}, {"que": "saldo_mayor_que", "valor": 5}]
    )
    assert result.summary["total"] == 0
    steps = [(s["criterio"][:12], s["personas"]) for s in result.summary["embudo"]]
    assert steps == [("partida (bas", 2), ("está de vaca", 1), ("saldo de vac", 0)]
