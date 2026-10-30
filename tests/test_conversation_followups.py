"""Seguimientos conversacionales sin criterio propio (CTX-002, Tarea 2).

El modo sombra detectó «quiénes son» devolviendo una población sin relación con el resultado
que se acababa de mostrar. La causa: `wants_previous` solo reconocía el resultado anterior si
el modelo marcaba `sobre_resultado_anterior` o si el mensaje decía literalmente «volviendo a
los de…» — el prompt (`describe_focus`) solo citaba «de esos/ellas» como disparador, así que
«quiénes son», «cuántos son» o «cuántas personas distintas representan» dependían enteramente
de que el modelo improvisara el flag correcto. Esta suite reproduce una conversación de varios
turnos con esas formulaciones y comprueba que el resultado es estable turno a turno, sin
necesitar `sobre_resultado_anterior=True` explícito.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry
from mia.llm import ToolCall
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database
from tests.hr_seed import TODAY, _emp, _shift

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


async def call(registry: ToolRegistry, name: str, state: dict[str, Any], mensaje: str = "", **args: Any) -> Any:
    """Un turno: ejecuta la herramienta y aplica sus state_updates al estado de sesión (como el motor real)."""
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state=state, user_message=mensaje)
    execution = await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)
    state.update(execution.result.state_updates)
    return execution.result


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "followups.db")
    rows = [
        _emp(1, "Marta Soto", "Pisos", person_key="pk-marta", email="marta@x.test"),
        _emp(2, "Nuria Ibáñez", "Pisos", person_key="pk-nuria", email="nuria@x.test"),
        _emp(3, "Olga Prats", "Pisos", person_key="pk-olga", email="olga@x.test"),
        _emp(4, "Pedro Ríos", "Cocina", person_key="pk-pedro", email="pedro@x.test"),
        _emp(5, "Rosa Vidal", "Cocina", person_key="pk-rosa", email="rosa@x.test"),
    ]
    async with db.session() as s:
        s.add_all(rows)
    registry = build_registry(db)
    yield registry
    await db.dispose()


@pytest.mark.parametrize(
    "followup",
    [
        "¿quiénes son?",
        "quienes son",
        "¿cuántos son?",
        "¿cuántas personas distintas representan?",
        "y cuántas personas distintas representan",
    ],
)
async def test_generic_followups_resolve_to_the_shown_population(registry: ToolRegistry, followup: str) -> None:
    """Turno 1 muestra Pisos (3); el turno 2, con cada formulación, debe referirse a esos 3, no a todos."""
    state: dict[str, Any] = {}
    first = await call(registry, "plantilla", state, departamento="Pisos")
    assert first.summary["total"] == 3

    second = await call(registry, "plantilla", state, mensaje=followup)
    names = {p["nombre"] for p in second.summary["personas"]}
    assert names == {"Marta Soto", "Nuria Ibáñez", "Olga Prats"}  # no las 5 personas de la plantilla


async def test_three_turn_conversation_stays_consistent(registry: ToolRegistry) -> None:
    """3 turnos encadenados: Pisos → «quiénes son» → «cuántos son» deben dar siempre el mismo total."""
    state: dict[str, Any] = {}
    first = await call(registry, "plantilla", state, departamento="Pisos")
    second = await call(registry, "plantilla", state, mensaje="¿quiénes son?")
    third = await call(registry, "plantilla", state, mensaje="¿cuántos son en total?")
    assert first.summary["total"] == second.summary["total"] == third.summary["total"] == 3


async def test_self_contained_question_is_not_hijacked_as_a_followup(registry: ToolRegistry) -> None:
    """CTX-001: una pregunta autocontenida con su propio criterio no hereda la población anterior,
    aunque empiece igual que un seguimiento genérico («quiénes son los empleados de Cocina»)."""
    state: dict[str, Any] = {}
    await call(registry, "plantilla", state, departamento="Pisos")
    fresh = await call(
        registry, "plantilla", state, mensaje="¿Quiénes son los empleados de Cocina?", departamento="Cocina"
    )
    names = {p["nombre"] for p in fresh.summary["personas"]}
    assert names == {"Pedro Ríos", "Rosa Vidal"}


async def test_followup_without_any_previous_result_is_a_clear_not_found(registry: ToolRegistry) -> None:
    state: dict[str, Any] = {}
    result = await call(registry, "plantilla", state, mensaje="¿quiénes son?")
    assert result.status.value == "not_found"


@pytest.mark.parametrize(
    "message", ["compara esas tres personas", "salario de estas 3 empleadas", "lista esos empleados"]
)
async def test_demonstrative_population_does_not_require_llm_flag(registry, message):
    state = {}
    await call(registry, "plantilla", state, departamento="Pisos")
    result = await call(registry, "plantilla", state, mensaje=message)
    assert {p["nombre"] for p in result.summary["personas"]} == {"Marta Soto", "Nuria Ibáñez", "Olga Prats"}


async def test_unknown_named_population_is_not_replaced_by_the_latest_group(registry):
    state = {}
    await call(registry, "plantilla", state, departamento="Pisos")
    result = await call(registry, "plantilla", state, resultado="grupo que no existe")
    assert result.status.value == "not_found"


async def test_truncated_population_is_not_used_as_complete(registry):
    state = {}
    await call(registry, "plantilla", state, departamento="Pisos")
    state["ultima_poblacion"]["empleado_ids"] = [1, 2]
    result = await call(registry, "plantilla", state, mensaje="¿quiénes son?")
    assert result.status.value == "not_found"


@pytest.mark.parametrize(
    "message",
    [
        "¿Qué empleados están trabajando ahora mismo?",
        "¿Quiénes están trabajando ahora?",
        "¿Quién trabaja en este momento?",
    ],
)
async def test_fresh_workforce_question_ignores_stale_model_filters_after_reopening(tmp_path, message):
    db = await fresh_database(tmp_path, "fresh-workforce.db")
    async with db.session() as session:
        session.add_all(
            [
                _emp(1, "Persona Alfa", "Pisos", person_key="alfa"),
                _emp(2, "Persona Beta", "Cocina", person_key="beta"),
                _shift(1, "alfa", "Persona Alfa", "Pisos", TODAY, "Trabajo", "07:00-15:00"),
                _shift(2, "beta", "Persona Beta", "Cocina", TODAY, "Trabajo", "07:00-15:00"),
            ]
        )
    await db.dispose()
    registry = build_registry(db)
    state = {
        "foco_departamento": "Pisos",
        "ultima_poblacion": {"total": 1, "empleado_ids": [1], "person_keys": ["alfa"]},
    }
    try:
        result = await call(
            registry,
            "turnos_dia",
            state,
            mensaje=message,
            departamento="Pisos",
            sobre_resultado_anterior=True,
            hora="23:00",
            franja="noche",
        )
        assert result.status.value == "ok"
        assert set(state["ultima_poblacion"]["empleado_ids"]) == {1, 2}
        assert state["foco_departamento"] is None
    finally:
        await db.dispose()
