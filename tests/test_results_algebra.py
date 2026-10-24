"""Operaciones sobre resultados anteriores, maestros documentales y exclusión de turnos con DNI discrepante."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.conversation.tools import HISTORY, LAST_TABLE, remember_population
from mia.data import Database
from mia.ingestion import Pseudonymizer
from mia.ingestion.mappers import hr
from mia.ingestion.mappers.common import MapContext
from mia.llm import ToolCall
from mia.modules.registry import build_registry

USER = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
TABLE = {
    "type": "table",
    "title": "Ausencias",
    "columns": ["Persona", "Departamento", "Días"],
    "rows": [[f"P{i}", "Pisos" if i % 3 else "Cocina", i] for i in range(1, 91)],
}


async def run(name: str, state: dict[str, Any], **args: Any) -> Any:
    registry = build_registry(Database("sqlite+aiosqlite:///:memory:"))
    ctx = ToolContext(user=USER, request_id=None, now=datetime.now(ZoneInfo("Europe/Madrid")), session_state=state)
    return (await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)).result


async def test_operations_over_a_long_previous_table() -> None:
    state = {LAST_TABLE: TABLE}
    assert (await run("operar_resultado", state, operacion="contar")).summary["filas"] == 90
    grouped = await run("operar_resultado", state, operacion="agrupar", columna="departamento")
    assert grouped.summary["grupos"] == {"Pisos": 60, "Cocina": 30}
    top = await run("operar_resultado", state, operacion="primeros", columna="días", n=3)
    assert [r[0] for r in top.summary["muestra"]] == ["P90", "P89", "P88"]
    filtered = await run("operar_resultado", state, operacion="filtrar", columna="Departamento", valor="cocina")
    assert filtered.summary["filas"] == 30


async def test_unknown_column_lists_the_available_ones() -> None:
    result = await run("operar_resultado", {LAST_TABLE: TABLE}, operacion="agrupar", columna="planeta")
    assert result.status is ToolStatus.INVALID_ARGUMENTS and "Persona" in result.summary["columnas"]


async def test_crossing_two_previous_results() -> None:
    state: dict[str, Any] = {}
    remember_population(
        state,
        {
            "etiqueta": "ausencias hoy",
            "total": 3,
            "empleado_ids": [1, 2, 3],
            "person_keys": ["a", "b", "c"],
            "emails": [],
        },
    )
    remember_population(
        state,
        {
            "etiqueta": "saldos 2026 negativos",
            "total": 2,
            "empleado_ids": [2, 9],
            "person_keys": ["b", "z"],
            "emails": [],
        },
    )
    both = await run("cruzar_resultados", state, a="ausencias", b="saldos", operacion="interseccion")
    assert both.summary["personas"] == 1
    assert both.state_updates["ultima_poblacion"]["empleado_ids"] == [2]
    only_a = await run("cruzar_resultados", state, a="ausencias", b="saldos", operacion="diferencia")
    assert only_a.summary["personas"] == 2
    assert len(state[HISTORY]) == 2


def test_shift_row_with_mismatching_folder_is_excluded() -> None:
    """Regla del sistema anterior: si el DNI del campo y el de la carpeta difieren, se excluye."""
    ctx = MapContext(tz=ZoneInfo("Europe/Madrid"), pseudonymize=Pseudonymizer("k"))
    row = {"ID": 1, "AnnoTurno": "2026", "SemanaTurno": "32", "DNIEmpleado": "pk-a", "_person_key": "pk-b"}
    with pytest.raises(ValueError, match="no coinciden"):
        hr.shift_week(row, ctx)
    assert len(hr.shift_week({**row, "_person_key": "pk-a"}, ctx)) == 7
