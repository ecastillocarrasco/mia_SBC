"""Operaciones sobre resultados anteriores, maestros documentales y exclusión de turnos con DNI discrepante."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import ConversationEngine, ToolContext, ToolStatus
from mia.conversation.tools import HISTORY, LAST_TABLE, Tool, ToolResult, remember_population
from mia.data import Database
from mia.ingestion import Pseudonymizer
from mia.ingestion.mappers import hr
from mia.ingestion.mappers.common import MapContext
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.registry import build_registry
from tests.dbutil import fresh_database

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
    truncated = {**TABLE, "__export_meta__": {"truncated": True}}
    assert (
        await run("operar_resultado", {LAST_TABLE: truncated}, operacion="agrupar", columna="Departamento")
    ).status is ToolStatus.INVALID_ARGUMENTS


async def test_filter_table_updates_the_exact_linked_population():
    state = {
        LAST_TABLE: {
            "type": "table",
            "columns": ["Persona", "Departamento"],
            "rows": [["Synthetic A", "Cocina"], ["Synthetic B", "Pisos"], ["Synthetic C", "Cocina"]],
        },
        "ultima_poblacion": {
            "etiqueta": "Original",
            "total": 3,
            "empleado_ids": [1, 2, 3],
            "miembros": [
                {"id": i, "nombre": f"Synthetic {letter}", "person_key": f"k{i}", "email": None}
                for i, letter in enumerate("ABC", start=1)
            ],
        },
    }
    result = await run("operar_resultado", state, operacion="filtrar", columna="Departamento", valor="Cocina")
    assert result.status is ToolStatus.OK
    assert result.state_updates["ultima_poblacion"]["empleado_ids"] == [1, 3]
    assert result.state_updates["ultima_poblacion"]["person_keys"] == ["k1", "k3"]
    assert result.state_updates["ultima_poblacion"]["total"] == 2
    state["ultima_poblacion"]["miembros"][1]["nombre"] = "Synthetic A"
    denied = await run("operar_resultado", state, operacion="filtrar", columna="Departamento", valor="Cocina")
    assert denied.status is ToolStatus.INVALID_ARGUMENTS
    assert not denied.state_updates


async def test_followup_distribution_groups_the_previous_table_without_another_model_call(tmp_path):
    class Params(BaseModel):
        pass

    async def staff(params, ctx):
        return ToolResult.ok(
            {},
            {
                "type": "table",
                "columns": ["Persona", "Puesto"],
                "rows": [["Synthetic A", "Recepción"], ["Synthetic B", "Recepción"], ["Synthetic C", "Conserje"]],
            },
        )

    actions = iter([tool_call("plantilla", {}), final_answer("Lista en pantalla", "Lista en pantalla")])
    provider = FakeLLMProvider(lambda request: next(actions))
    db = await fresh_database(tmp_path)
    try:
        registry = build_registry(db)
        registry._tools["plantilla"] = Tool("plantilla", "Plantilla", Params, staff)
        engine = ConversationEngine(llm=provider, tools=registry, db=db)
        initial = await engine.complete(message="Lista la plantilla", user=USER, session_id=None)
        calls = len(provider.requests)
        result = await engine.complete(
            message="Muéstrame también su distribución por puesto.", user=USER, session_id=initial.session_id
        )
        assert result.status == "ok"
        assert result.presentations[0]["columns"] == ["Puesto", "Total"]
        assert result.presentations[0]["rows"] == [["Recepción", 2], ["Conserje", 1]]
        assert len(provider.requests) == calls
    finally:
        await db.dispose()


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
    assert both.state_updates["ultima_poblacion"]["person_keys"] == ["b"]
    only_a = await run("cruzar_resultados", state, a="ausencias", b="saldos", operacion="diferencia")
    assert only_a.summary["personas"] == 2
    assert only_a.state_updates["ultima_poblacion"]["person_keys"] == ["a", "c"]
    assert len(state[HISTORY]) == 2


async def test_crossing_rejects_truncated_or_unlinked_population_instead_of_broadening_it():
    state = {
        HISTORY: [
            {"etiqueta": "A", "total": 3, "empleado_ids": [1, 2], "person_keys": ["k1", "k2"]},
            {"etiqueta": "B", "total": 1, "empleado_ids": [2], "person_keys": ["k2"]},
        ]
    }
    assert (await run("cruzar_resultados", state, a="A", b="B")).status is ToolStatus.INVALID_ARGUMENTS
    state[HISTORY][0]["total"] = 2
    state[HISTORY][0]["person_keys"] = ["k2"]
    assert (await run("cruzar_resultados", state, a="A", b="B")).status is ToolStatus.INVALID_ARGUMENTS


async def test_crossing_keeps_identity_links_when_some_people_have_no_key_or_email():
    state = {
        HISTORY: [
            {
                "etiqueta": "A",
                "total": 2,
                "empleado_ids": [1, 2],
                "miembros": [
                    {"id": 1, "person_key": None, "email": None},
                    {"id": 2, "person_key": "k2", "email": "synthetic@example.test"},
                ],
            },
            {
                "etiqueta": "B",
                "total": 1,
                "empleado_ids": [2],
                "person_keys": ["k2"],
                "emails": ["synthetic@example.test"],
            },
        ]
    }
    result = await run("cruzar_resultados", state, a="A", b="B")
    population = result.state_updates["ultima_poblacion"]
    assert population["empleado_ids"] == [2] and population["person_keys"] == ["k2"]
    assert population["emails"] == ["synthetic@example.test"]


def test_shift_row_with_mismatching_folder_is_excluded() -> None:
    """Regla del sistema anterior: si el DNI del campo y el de la carpeta difieren, se excluye."""
    ctx = MapContext(tz=ZoneInfo("Europe/Madrid"), pseudonymize=Pseudonymizer("k"))
    row = {"ID": 1, "AnnoTurno": "2026", "SemanaTurno": "32", "DNIEmpleado": "pk-a", "_person_key": "pk-b"}
    with pytest.raises(ValueError, match="no coinciden"):
        hr.shift_week(row, ctx)
    assert len(hr.shift_week({**row, "_person_key": "pk-a"}, ctx)) == 7
