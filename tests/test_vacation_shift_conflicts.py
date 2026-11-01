"""El cruce exige misma persona, mismo día y todas las fuentes autorizadas."""

import json
from datetime import date

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.data import Database, Vacation
from mia.llm import ToolCall
from mia.modules.rrhh import build_rrhh_registry
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, _shift
from tests.test_domains import NOW

ADMIN = UserContext("test", "Test", roles=frozenset({"mia.admin"}))
NAME = "cruce_vacaciones_turnos"


async def execute(registry, user=ADMIN, message="", **args):
    context = ToolContext(user=user, request_id=None, now=NOW, session_state={}, user_message=message)
    return (await registry.execute(ToolCall("call", NAME, json.dumps(args)), context)).result


@pytest.mark.parametrize(
    ("same_day", "status", "kind", "expected"),
    [
        (True, "Aceptada", "Trabajo", 1),
        (False, "Aceptada", "Trabajo", 0),
        (True, "Pendiente de firma", "Trabajo", 0),
        (True, "Rechazada", "Trabajo", 0),
        (True, "Aceptada", "Descanso", 0),
    ],
)
async def test_whole_week_conflict_in_last_day_not_population_intersection(tmp_path, same_day, status, kind, expected):
    db = await fresh_database(tmp_path)
    try:
        async with db.session() as session:
            session.add(_emp(1, "Persona sintética", "Cocina", email="a@example.invalid", person_key="a"))
            session.add(_shift(1, "a", "Persona sintética", "Cocina", date(2026, 8, 9), kind, "9-17"))
            session.add(
                Vacation(
                    sp_id=1,
                    employee_email="a@example.invalid",
                    request_type="Vacaciones",
                    status=status,
                    start_date=date(2026, 8, 9 if same_day else 3),
                    end_date=date(2026, 8, 9 if same_day else 3),
                )
            )
        result = await execute(build_rrhh_registry(db), departamento="Cocina", desde="2026-08-03", hasta="2026-08-09")
        assert result.status is ToolStatus.OK
        assert result.summary["dias_consultados"] == 7
        assert result.summary["personas_con_conflicto"] == expected
        assert result.summary["conflictos_por_fecha"] == ({"2026-08-09": 1} if expected else {})
        assert result.summary["dias_persona_sin_turno_publicado"] == 6
        assert result.summary["limitacion"]
    finally:
        await db.dispose()


@pytest.mark.parametrize("role", ["Administracion", "Legal", "mia.seleccion"])
async def test_cross_source_permissions_apply_to_catalog_and_execution(role):
    db = Database("sqlite+aiosqlite:///:memory:")
    registry = build_rrhh_registry(db)
    user = UserContext("restricted", "Test", roles=frozenset({role}))
    try:
        assert NAME not in {schema.name for schema in registry.schemas_for(user)}
        result = await execute(registry, user, desde="2026-08-03", hasta="2026-08-09")
        assert result.status is ToolStatus.PERMISSION_DENIED
    finally:
        await db.dispose()


@pytest.mark.parametrize("duplicate", ["key", "email"])
async def test_ambiguous_identities_are_not_silently_associated(tmp_path, duplicate):
    db = await fresh_database(tmp_path)
    try:
        async with db.session() as session:
            session.add(_emp(1, "Persona A", "Cocina", email="a@example.invalid", person_key="a"))
            session.add(
                _emp(
                    2,
                    "Persona B",
                    "Cocina",
                    email="A@example.invalid" if duplicate == "email" else "b@example.invalid",
                    person_key="a" if duplicate == "key" else "b",
                )
            )
        result = await execute(build_rrhh_registry(db), departamento="Cocina", desde="2026-08-03", hasta="2026-08-09")
        assert result.status is ToolStatus.INVALID_ARGUMENTS
        assert not result.state_updates
    finally:
        await db.dispose()


@pytest.mark.parametrize("missing", ["empleados", "turnos", "vacaciones"])
def test_cross_tool_not_offered_when_a_source_domain_is_disabled(missing):
    registry = build_rrhh_registry(
        Database("sqlite+aiosqlite:///:memory:"),
        enabled=[domain for domain in ("empleados", "turnos", "vacaciones") if domain != missing],
    )
    assert NAME not in {schema.name for schema in registry.schemas_for(ADMIN)}


async def test_current_week_rejects_wrong_model_dates_before_querying_sources():
    db = Database("sqlite+aiosqlite:///:memory:")
    try:
        result = await execute(
            build_rrhh_registry(db),
            message="Cruza vacaciones y turnos de esta semana",
            desde="2026-08-09",
            hasta="2026-08-15",
        )
        assert result.status is ToolStatus.INVALID_ARGUMENTS
        assert result.summary["desde_requerido"] == "2026-08-03"
        assert result.summary["hasta_requerido"] == "2026-08-09"
    finally:
        await db.dispose()


async def test_current_week_without_dates_includes_whole_calendar_week(tmp_path):
    db = await fresh_database(tmp_path)
    try:
        result = await execute(build_rrhh_registry(db), message="Cruza vacaciones y turnos de esta semana")
        assert result.status is ToolStatus.OK
        assert result.summary["desde"] == "2026-08-03"
        assert result.summary["hasta"] == "2026-08-09"
        assert result.summary["dias_consultados"] == 7
    finally:
        await db.dispose()
