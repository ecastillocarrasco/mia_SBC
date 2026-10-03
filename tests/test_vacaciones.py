"""Vacaciones «en firme» (`confirmed_vacations`, común a los 7 sitios que antes usaban `is_operational`).

Aceptada/Aprobada siempre cuentan. Pendiente de firma solo cuenta cuando el turno ya refleja
Vacaciones en el periodo exacto de esa solicitud; si solo hay solicitud y ningún turno que la
respalde, o el turno cae fuera del periodo pedido, todavía no cuenta (VAC-002, REI-001).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry
from mia.data import Vacation
from mia.llm import ToolCall
from mia.modules.rrhh import build_registry
from mia.modules.rrhh.common import confirmed_vacations
from tests.dbutil import fresh_database
from tests.hr_seed import TODAY, _emp, _shift

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
d = lambda n: TODAY + timedelta(days=n)  # noqa: E731


async def call(registry: ToolRegistry, name: str, **args: Any) -> Any:
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    execution = await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)
    return execution.result


def _vac(sp: int, email: str, name: str, status: str, a: int, b: int) -> Vacation:  # noqa: PLR0917
    return Vacation(
        sp_id=sp,
        employee_email=email,
        employee_name=name,
        department="Pisos",
        department_key="pisos",
        status=status,
        request_type="Vacaciones",
        start_date=d(a),
        end_date=d(b),
        total_days=b - a + 1,
    )


@pytest.fixture
async def scenario(tmp_path: Path) -> AsyncIterator[tuple[ToolRegistry, Any]]:
    db = await fresh_database(tmp_path, "vac_confirmadas.db")
    rows: list[Any] = [
        _emp(1, "Ana", "Pisos", person_key="pk-ana", email="ana@x.test"),  # aceptada, sin turno: cuenta igual
        _emp(2, "Beto", "Pisos", person_key="pk-beto", email="beto@x.test"),  # pendiente, turno la respalda
        _emp(3, "Cris", "Pisos", person_key="pk-cris", email="cris@x.test"),  # pendiente, sin turno
        _emp(4, "Dani", "Pisos", person_key="pk-dani", email="dani@x.test"),  # pendiente, turno fuera de periodo
        _vac(1, "ana@x.test", "Ana", "Aceptada", 1, 3),
        _vac(2, "beto@x.test", "Beto", "Pendiente Firma", 1, 3),
        _vac(3, "cris@x.test", "Cris", "Pendiente Firma", 1, 3),
        _vac(4, "dani@x.test", "Dani", "Pendiente Firma", 1, 3),
        _shift(1, "pk-beto", "Beto", "Pisos", d(2), "Vacaciones", "Vacaciones", email="beto@x.test"),
        _shift(2, "pk-dani", "Dani", "Pisos", d(10), "Vacaciones", "Vacaciones", email="dani@x.test"),  # fuera
    ]
    async with db.session() as s:
        s.add_all(rows)
    registry = build_registry(db)
    yield registry, db
    await db.dispose()


async def test_confirmed_vacations_filters_by_shift_backing(scenario: tuple[ToolRegistry, Any]) -> None:
    """Unidad: `confirmed_vacations` sobre las 4 solicitudes del escenario."""
    _, db = scenario
    async with db.session() as s:
        rows = list((await s.scalars(select(Vacation).order_by(Vacation.sp_id))).all())
        confirmed = await confirmed_vacations(s, rows)
    assert sorted(v.employee_name for v in confirmed) == ["Ana", "Beto"]


async def test_vacaciones_tool_aceptadas_applies_same_criterion(scenario: tuple[ToolRegistry, Any]) -> None:
    """Integración: la herramienta `vacaciones` (estado=aceptadas) ve lo mismo que la función común."""
    registry, _ = scenario
    result = await call(registry, "vacaciones", estado="aceptadas", desde=d(1).isoformat(), hasta=d(3).isoformat())
    names = {i["persona"] for i in result.summary["detalle"]}
    assert names == {"Ana", "Beto"}  # Cris (sin turno) y Dani (turno fuera de periodo) no cuentan


async def test_pending_without_shift_still_appears_with_estado_todas(scenario: tuple[ToolRegistry, Any]) -> None:
    """Cris y Dani no desaparecen del sistema: el filtro de «en firme» solo aplica a estado=aceptadas."""
    registry, _ = scenario
    result = await call(registry, "vacaciones", estado="todas", desde=d(1).isoformat(), hasta=d(3).isoformat())
    names = {i["persona"] for i in result.summary["detalle"]}
    assert names == {"Ana", "Beto", "Cris", "Dani"}


async def test_no_pending_requests_is_a_cheap_no_op() -> None:
    """Sin solicitudes pendientes de firma, no se lanza ninguna consulta de turnos."""

    class _ExplodingSession:
        async def execute(self, *a: object, **kw: object) -> Any:
            raise AssertionError("no debería consultar ShiftDay si no hay pendientes de firma")

    confirmed = await confirmed_vacations(
        _ExplodingSession(),  # type: ignore[arg-type]
        [_vac(1, "ana@x.test", "Ana", "Aceptada", 1, 3), _vac(2, "x@x.test", "X", "Rechazada", 1, 3)],
    )
    assert [v.employee_name for v in confirmed] == ["Ana"]
