import pytest
from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import ConversationEngine
from mia.conversation.tools import Tool, ToolRegistry, ToolResult, ToolStatus
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.rrhh.common import previous_population
from tests.dbutil import fresh_database


class Params(BaseModel):
    pass


@pytest.mark.parametrize("source_status", [ToolStatus.OK, ToolStatus.SOURCE_UNAVAILABLE])
async def test_omitted_planned_read_is_completed_once_and_source_failure_is_not_retried(tmp_path, source_status):
    calls = []

    async def read(params, ctx):
        calls.append(True)
        return ToolResult(source_status, {"count": 3})

    registry = ToolRegistry()
    registry.register(Tool("turnos_dia", "Turnos", Params, read))
    actions = iter(
        [
            tool_call(
                "planificar_tarea", {"pasos": [{"objetivo": "Consultar turnos", "herramientas": ["turnos_dia"]}]}
            ),
            final_answer("No he consultado la fuente", "No he consultado la fuente"),
        ]
    )
    provider = FakeLLMProvider(lambda request: next(actions, final_answer("Sin fuente", "Sin fuente")))
    db = await fresh_database(tmp_path)
    try:
        result = await ConversationEngine(llm=provider, tools=registry, db=db).complete(
            message="Analiza los turnos", user=UserContext("u", "Synthetic"), session_id=None
        )
        assert calls == [True]
        assert result.status == ("ok" if source_status is ToolStatus.OK else "error")
        if source_status is ToolStatus.OK:
            assert "He completado las lecturas" in result.answer
            assert "No he consultado" not in result.answer
    finally:
        await db.dispose()


async def test_followup_uses_entry_population_after_an_intermediate_query_replaces_state(tmp_path):
    calls = []
    original = {"total": 3, "empleado_ids": [1, 2, 3], "etiqueta": "Synthetic original"}
    replacement = {"total": 4, "empleado_ids": [4, 5, 6, 7], "etiqueta": "Synthetic replacement"}

    async def staff(params, ctx):
        population = original if not calls else replacement
        calls.append("staff")
        return ToolResult(ToolStatus.OK, {}, state_updates={"ultima_poblacion": population})

    async def salary(params, ctx):
        selected = previous_population(ctx)
        assert selected is not None and selected["empleado_ids"] == [1, 2, 3]
        calls.append("salary")
        return ToolResult.ok({"personas": 3})

    actions = iter(
        [
            tool_call("plantilla", {}),
            final_answer("Grupo en pantalla", "Grupo en pantalla"),
            tool_call(
                "planificar_tarea",
                {
                    "pasos": [
                        {"objetivo": "Actualizar contexto", "herramientas": ["plantilla"]},
                        {
                            "objetivo": "Comparar el grupo original",
                            "herramientas": ["comparativa_salarial"],
                            "depende_de": [0],
                        },
                    ]
                },
            ),
            tool_call("plantilla", {}),
            final_answer("Comparación pendiente", "Comparación pendiente"),
        ]
    )
    registry = ToolRegistry()
    registry.register(Tool("plantilla", "Plantilla", Params, staff))
    registry.register(Tool("comparativa_salarial", "Comparativa", Params, salary))
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda request: next(actions, final_answer("Pendiente", "Pendiente"))),
            tools=registry,
            db=db,
        )
        initial = await engine.complete(
            message="Lista la plantilla", user=UserContext("u", "Synthetic"), session_id=None
        )
        result = await engine.complete(
            message="Compara el salario de esas personas",
            user=UserContext("u", "Synthetic"),
            session_id=initial.session_id,
        )
        assert result.status == "ok"
        assert calls == ["staff", "staff", "salary"]
    finally:
        await db.dispose()
