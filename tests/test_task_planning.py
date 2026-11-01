from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from mia.auth import UserContext
from mia.conversation import ConversationEngine
from mia.conversation.events import ResultEvent, SpeechEvent
from mia.conversation.planning import PLAN_TOOL, TaskPlan, TaskSteps, recovery_tools
from mia.conversation.tools import Tool, ToolContext, ToolExecution, ToolRegistry, ToolResult, ToolStatus
from mia.llm import ToolCall, ToolSchema
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from tests.dbutil import fresh_database


def execution(name, status=ToolStatus.OK):
    return ToolExecution(ToolCall(name, name, "{}"), ToolResult(status, {}), 0, None)


async def test_long_reviewed_reads_do_not_prevent_completing_both_planned_periods(tmp_path):
    class Params(BaseModel):
        periodo: str

    queried = []

    async def read(params, ctx):
        await asyncio.sleep(0.25)
        queried.append(params.periodo)
        return ToolResult.ok({"periodo": params.periodo, "total": 30})

    registry = ToolRegistry()
    registry.register(Tool("analisis_economico_nominas", "Consultar periodo", Params, read))
    actions = [
        tool_call(
            PLAN_TOOL,
            {
                "pasos": [
                    {
                        "objetivo": f"Consultar {year}",
                        "herramientas": ["analisis_economico_nominas"],
                        "argumentos": {"analisis_economico_nominas": {"periodo": year}},
                    }
                    for year in ("2025", "2026")
                ]
            },
        ),
        tool_call("analisis_economico_nominas", {"periodo": "2025"}, call_id="year_1"),
        tool_call("analisis_economico_nominas", {"periodo": "2026"}, call_id="year_2"),
        final_answer("Se consultaron ambos años.", "Consulta completada"),
    ]
    provider = FakeLLMProvider(lambda request: actions.pop(0))
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(llm=provider, tools=registry, db=db, turn_budget_seconds=0.2)
        result = await engine.complete(
            message="Compara los dos años", user=UserContext("u", "Usuario"), session_id=None
        )
        assert result.status == "ok"
        assert queried == ["2025", "2026"]
        assert result.elapsed_ms >= 500
    finally:
        await db.dispose()


async def test_write_wait_does_not_extend_budget_or_allow_a_repeated_write(tmp_path):
    class Params(BaseModel):
        pass

    writes = []

    async def send(params, ctx):
        writes.append(True)
        await asyncio.sleep(0.25)
        return ToolResult.ok({"enviado": True})

    registry = ToolRegistry()
    registry.register(Tool("enviar_correo", "Enviar", Params, send))
    provider = FakeLLMProvider(lambda request: tool_call("enviar_correo", {}))
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(llm=provider, tools=registry, db=db, turn_budget_seconds=0.2)
        result = await engine.complete(
            message="Envía el correo confirmado", user=UserContext("u", "Usuario"), session_id=None
        )
        assert writes == [True]
        assert result.status == "error"
    finally:
        await db.dispose()


def test_plan_needs_real_successful_tools_in_dependency_order():
    plan = TaskPlan("Compara datos", frozenset({"leer", "analizar"}))
    plan.steps = TaskSteps.model_validate(
        {
            "pasos": [
                {"objetivo": "Consultar", "herramientas": ["leer"]},
                {"objetivo": "Comparar", "herramientas": ["analizar"], "depende_de": [0]},
            ]
        }
    ).pasos
    assert len(plan.missing([])) == 2
    assert plan.missing([execution("leer"), execution("analizar", ToolStatus.ERROR)])
    assert plan.missing([execution("analizar"), execution("leer")])
    assert plan.missing([execution("leer"), execution("analizar")]) == []


def test_success_with_wrong_population_filter_does_not_complete_the_step():
    plan = TaskPlan("Analiza Cocina", frozenset({"plantilla"}))
    plan.steps = TaskSteps.model_validate(
        {
            "pasos": [
                {
                    "objetivo": "Consultar Cocina",
                    "herramientas": ["plantilla"],
                    "argumentos": {"plantilla": {"departamento": "Cocina"}},
                }
            ]
        }
    ).pasos
    wrong = ToolExecution(ToolCall("c", "plantilla", '{"departamento":"Recepción"}'), ToolResult.ok({}), 0, None)
    right = ToolExecution(ToolCall("c", "plantilla", '{"departamento":"Cocina"}'), ToolResult.ok({}), 0, None)
    assert plan.missing([wrong])
    assert plan.missing([right]) == []


def test_plan_cannot_remove_the_requested_files():
    plan = TaskPlan("Genera PDF y Excel", frozenset())
    assert set(plan.missing([])) == {"archivo pdf pendiente", "archivo xlsx pendiente"}


def test_plan_describes_the_authorized_catalog_beyond_initial_routing():
    description = TaskPlan("Cruza fuentes", frozenset({"plantilla", "consulta_agenda"})).tool().description
    assert "plantilla" in description
    assert "consulta_agenda" in description
    assert "enviar_correo" not in description


def test_planning_schema_limits_names_to_real_authorized_tools():
    schema = TaskPlan("Cruza fuentes", frozenset({"plantilla", "vacaciones"})).tool().schema().parameters
    assert schema["$defs"]["TaskStep"]["properties"]["herramientas"]["items"]["enum"] == ["plantilla", "vacaciones"]


def test_single_tool_flat_arguments_are_preserved_and_enforced():
    plan = TaskPlan("Analiza Cocina", frozenset({"plantilla"}))
    plan.steps = TaskSteps.model_validate(
        {"pasos": [{"objetivo": "Consultar", "herramientas": ["plantilla"], "argumentos": {"departamento": "Cocina"}}]}
    ).pasos
    assert plan.steps[0].argumentos == {"plantilla": {"departamento": "Cocina"}}
    assert plan.missing([execution("plantilla")])
    right = ToolExecution(ToolCall("c", "plantilla", '{"departamento":"Cocina"}'), ToolResult.ok({}), 0, None)
    assert plan.missing([right]) == []


def test_flat_filters_for_multiple_tools_are_rejected_instead_of_guessed():
    with pytest.raises(ValidationError, match="por herramienta"):
        TaskSteps.model_validate(
            {
                "pasos": [
                    {
                        "objetivo": "Consultar",
                        "herramientas": ["plantilla", "vacaciones"],
                        "argumentos": {"departamento": "Cocina"},
                    }
                ]
            }
        )


async def test_missing_previous_group_asks_for_selection_without_model_or_source_access(tmp_path):
    db = await fresh_database(tmp_path)
    provider = FakeLLMProvider(lambda request: pytest.fail("No debe inventar ni consultar una población"))
    try:
        engine = ConversationEngine(llm=provider, tools=ToolRegistry(), db=db)
        result = await engine.complete(
            message="Compara el salario del grupo anterior, sin inventar una selección.",
            user=UserContext("u", "Usuario"),
            session_id=None,
        )
        assert result.status == "ok"
        assert "No hay una selección anterior" in result.answer
        assert result.tools == []
        assert provider.requests == []
    finally:
        await db.dispose()


def test_cycles_and_forward_dependencies_are_invalid():
    with pytest.raises(ValidationError):
        TaskSteps.model_validate({"pasos": [{"objetivo": "Ciclo", "herramientas": ["leer"], "depende_de": [0]}]})


async def test_planning_cannot_grant_tools_and_has_bounded_revisions():
    plan = TaskPlan("Analiza", frozenset({"leer"}))
    registry = ToolRegistry()
    registry.register(plan.tool())
    ctx = ToolContext(UserContext("u", "Usuario"), None, datetime.now(UTC))

    async def propose(name):
        args = {"pasos": [{"objetivo": "Consultar", "herramientas": [name]}]}
        return (await registry.execute(ToolCall("p", "planificar_tarea", json.dumps(args)), ctx)).result.status

    assert await propose("sin_permiso") is ToolStatus.INVALID_ARGUMENTS
    assert plan.steps == []
    assert await propose("leer") is ToolStatus.OK
    assert await propose("leer") is ToolStatus.OK
    assert await propose("leer") is ToolStatus.INVALID_ARGUMENTS


def test_recovery_never_offers_writes_or_unreviewed_tools():
    tools = [
        ToolSchema(name, "", {}) for name in ("consulta_agenda", "ejecutar_propuesta_agenda", "enviar_correo", "nueva")
    ]
    assert [tool.name for tool in recovery_tools(tools)] == ["consulta_agenda"]


async def test_real_conversation_replans_instead_of_speaking_false_completion(tmp_path):
    db = await fresh_database(tmp_path)
    registry = ToolRegistry()

    class Params(BaseModel):
        pass

    async def read(params, ctx):
        return ToolResult.ok({"total": 3})

    registry.register(Tool("plantilla", "Consultar plantilla", Params, read))

    def script(request):
        if not any(message.tool_calls for message in request.messages):
            return tool_call(
                "planificar_tarea", {"pasos": [{"objetivo": "Consultar plantilla", "herramientas": ["plantilla"]}]}
            )
        if request.messages[-1].content.startswith("VERIFICACIÓN DEL PLAN"):
            return tool_call("plantilla", {})
        if request.messages[-1].tool_call_id == "call_1" and '"total": 3' in request.messages[-1].content:
            return final_answer("Hay 3 personas", "Consulta completada")
        return final_answer("Todo completado sin consultar", "Afirmación sin evidencia")

    try:
        provider = FakeLLMProvider(script)
        engine = ConversationEngine(llm=provider, tools=registry, db=db, max_tool_rounds=5)
        events = [
            event
            async for event in engine.run(
                message="Analiza la plantilla", user=UserContext("u", "Usuario"), session_id=None
            )
        ]
        result = next(event.result for event in events if isinstance(event, ResultEvent))
        assert result.answer == "Hay 3 personas"
        assert "Afirmación sin evidencia" not in [event.text for event in events if isinstance(event, SpeechEvent)]
        assert any(
            message.content.startswith("VERIFICACIÓN DEL PLAN") for req in provider.requests for message in req.messages
        )
    finally:
        await db.dispose()


@pytest.mark.parametrize("attempt_write", [False, True])
async def test_complex_request_cannot_skip_plan_or_execute_before_planning(tmp_path, attempt_write):
    class Params(BaseModel):
        pass

    called = []

    async def handler(params, ctx):
        called.append(True)
        return ToolResult.ok({})

    registry = ToolRegistry()
    registry.register(Tool("enviar_correo", "Enviar correo", Params, handler))
    provider = FakeLLMProvider(
        lambda request: (
            tool_call("enviar_correo", {})
            if attempt_write
            else final_answer("Análisis completado", "Análisis completado")
        )
    )
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(llm=provider, tools=registry, db=db, max_tool_rounds=3)
        events = [
            event
            async for event in engine.run(
                message="Analiza la plantilla", user=UserContext("u", "Usuario"), session_id=None
            )
        ]
        result = next(event.result for event in events if isinstance(event, ResultEvent))
        assert called == []
        assert result.status == "error"
        assert "Análisis completado" not in [event.text for event in events if isinstance(event, SpeechEvent)]
        assert len(provider.requests) <= 4
    finally:
        await db.dispose()


async def test_skipped_plan_can_be_corrected_before_executing(tmp_path):
    class Params(BaseModel):
        pass

    called = []

    async def read(params, ctx):
        called.append(True)
        return ToolResult.ok({"total": 3})

    actions = iter(
        [
            tool_call("plantilla", {}),
            tool_call("planificar_tarea", {"pasos": [{"objetivo": "Consultar", "herramientas": ["plantilla"]}]}),
            tool_call("plantilla", {}),
            final_answer("Hay 3 personas", "Consulta completada"),
        ]
    )
    registry = ToolRegistry()
    registry.register(Tool("plantilla", "Consultar", Params, read))
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(llm=FakeLLMProvider(lambda request: next(actions)), tools=registry, db=db)
        result = await engine.complete(
            message="Analiza la plantilla", user=UserContext("u", "Usuario"), session_id=None
        )
        assert called == [True]
        assert result.answer == "Hay 3 personas"
    finally:
        await db.dispose()


async def test_model_latency_cannot_execute_tools_after_turn_deadline(tmp_path):
    class Params(BaseModel):
        pass

    called = []

    async def handler(params, ctx):
        called.append(True)
        return ToolResult.ok({})

    class SlowProvider(FakeLLMProvider):
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                assert request.tools, "La prueba debe alcanzar el modelo antes de agotar el presupuesto"
                await asyncio.sleep(0.3)
                events = tool_call("plantilla", {})
            else:
                events = final_answer("Consulta terminada", "Listo")
            for event in events:
                yield event

    registry = ToolRegistry()
    registry.register(Tool("plantilla", "Consultar", Params, handler))
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(llm=SlowProvider(), tools=registry, db=db, turn_budget_seconds=0.25)
        result = await engine.complete(message="Lista la plantilla", user=UserContext("u", "Usuario"), session_id=None)
        assert called == []
        assert result.status == "error"
    finally:
        await db.dispose()


async def test_registry_does_not_execute_a_tool_excluded_from_recovery():
    class Params(BaseModel):
        pass

    called = []

    async def send(params, ctx):
        called.append(True)
        return ToolResult.ok({})

    registry = ToolRegistry()
    registry.register(Tool("enviar_correo", "Enviar", Params, send))
    ctx = ToolContext(UserContext("u", "Usuario"), None, datetime.now(UTC))
    result = await registry.execute(ToolCall("c", "enviar_correo", "{}"), ctx, allowed_names={"plantilla"})
    assert result.result.status is ToolStatus.ERROR
    assert called == []


async def test_scheduler_orders_dependencies_before_running_their_handlers():
    class Params(BaseModel):
        pass

    executed = []

    async def source(params, ctx):
        executed.append("leer")
        return ToolResult.ok({"total": 3})

    async def analysis(params, ctx):
        assert executed == ["leer"]
        executed.append("analizar")
        return ToolResult.ok({"total": 3})

    registry = ToolRegistry()
    registry.register(Tool("leer", "Fuente", Params, source))
    registry.register(Tool("analizar", "Análisis", Params, analysis))
    plan = TaskPlan("Analiza", frozenset(registry.names()))
    plan.steps = TaskSteps.model_validate(
        {
            "pasos": [
                {"objetivo": "Obtener datos", "herramientas": ["leer"]},
                {"objetivo": "Analizar datos", "herramientas": ["analizar"], "depende_de": [0]},
            ]
        }
    ).pasos
    ctx = ToolContext(UserContext("u", "Usuario"), None, datetime.now(UTC))
    calls = [ToolCall("a", "analizar", "{}"), ToolCall("b", "leer", "{}")]
    results = await plan.execute(registry, calls, ctx, [], set(registry.names()))
    assert executed == ["leer", "analizar"]
    assert [result.call.call_id for result in results] == ["a", "b"]
    assert plan.missing(results) == []


async def test_pending_dependency_prevents_execution_instead_of_just_warning_afterwards():
    class Params(BaseModel):
        pass

    called = []

    async def handler(params, ctx):
        called.append(True)
        return ToolResult.ok({})

    registry = ToolRegistry()
    registry.register(Tool("analizar", "Análisis", Params, handler))
    plan = TaskPlan("Analiza", frozenset({"leer", "analizar"}))
    plan.steps = TaskSteps.model_validate(
        {
            "pasos": [
                {"objetivo": "Obtener datos", "herramientas": ["leer"]},
                {"objetivo": "Analizar datos", "herramientas": ["analizar"], "depende_de": [0]},
            ]
        }
    ).pasos
    ctx = ToolContext(UserContext("u", "Usuario"), None, datetime.now(UTC))
    results = await plan.execute(registry, [ToolCall("a", "analizar", "{}")], ctx, [], {"analizar"})
    assert called == []
    assert results[0].result.status is ToolStatus.INVALID_ARGUMENTS


@pytest.mark.parametrize("exhaust_budget", [False, True])
async def test_replanning_or_exhausted_budget_cannot_trigger_unverified_writes(tmp_path, exhaust_budget):
    class Params(BaseModel):
        pass

    called = []

    async def handler(params, ctx):
        called.append(True)
        return ToolResult.ok({})

    registry = ToolRegistry()
    registry.register(Tool("plantilla", "Leer plantilla", Params, handler))
    registry.register(Tool("enviar_correo", "Enviar correo", Params, handler))
    actions = [
        tool_call("planificar_tarea", {"pasos": [{"objetivo": "Obtener evidencia", "herramientas": ["plantilla"]}]}),
        tool_call("enviar_correo", {}) if exhaust_budget else final_answer("Todo completado", "Todo completado"),
        tool_call(
            "planificar_tarea", {"pasos": [{"objetivo": "Obtener evidencia", "herramientas": ["enviar_correo"]}]}
        ),
        tool_call("enviar_correo", {}),
        final_answer("Todo completado", "Todo completado"),
    ]
    index = 0

    def script(request):
        nonlocal index
        action = actions[min(index, len(actions) - 1)]
        index += 1
        return action

    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(script), tools=registry, db=db, max_tool_rounds=1 if exhaust_budget else 6
        )
        result = await engine.complete(
            message="Analiza la plantilla", user=UserContext("u", "Usuario"), session_id=None
        )
        assert called == []
        assert result.status == "error"
        assert "complet" in result.answer.lower()
    finally:
        await db.dispose()


async def test_optional_plan_is_offered_and_verified_for_an_unclassified_request(tmp_path):
    class Params(BaseModel):
        pass

    called = []

    async def read(params, ctx):
        called.append(True)
        return ToolResult.ok({"total": 3})

    registry = ToolRegistry()
    registry.register(Tool("plantilla", "Consultar plantilla", Params, read))

    def script(request):
        assert any(schema.name == PLAN_TOOL for schema in request.tools)
        completed = sum(message.role == "tool" for message in request.messages)
        if completed == 0:
            return tool_call(PLAN_TOOL, {"pasos": [{"objetivo": "Consultar datos", "herramientas": ["plantilla"]}]})
        if completed == 1:
            return tool_call("plantilla", {})
        return final_answer("Hay 3 personas", "Consulta completada")

    db = await fresh_database(tmp_path)
    try:
        provider = FakeLLMProvider(script)
        engine = ConversationEngine(llm=provider, tools=registry, db=db, max_tool_rounds=5)
        result = await engine.complete(message="Consulta los datos", user=UserContext("u", "Usuario"), session_id=None)
        assert called == [True]
        assert result.status == "ok"
        assert result.answer == "Hay 3 personas"
        assert len(provider.requests) == 3
    finally:
        await db.dispose()
