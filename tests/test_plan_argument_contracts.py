"""Planning uses real schemas and preserves data scope during report recovery."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import ConversationEngine
from mia.conversation.events import ResultEvent
from mia.conversation.planning import TaskPlan, TaskSteps
from mia.conversation.tools import Tool, ToolContext, ToolExecution, ToolRegistry, ToolResult, ToolStatus
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.rrhh.informes.tools import InformeEjecutivoParams, InformeParams
from tests.dbutil import fresh_database

CTX = ToolContext(UserContext("synthetic", "Test"), None, datetime.now(UTC))


class SourceParams(BaseModel):
    departamento: str | None = None
    incluir_inactivos: bool = False


@pytest.mark.parametrize("source_ok,export_ok", [(True, True), (False, True), (True, False)])
async def test_delivery_rechecks_the_plan_and_preserves_options_without_masking_missing_sources(
    tmp_path, source_ok, export_ok
):
    db = await fresh_database(tmp_path)
    registry = ToolRegistry()
    rendered = []

    async def source(params, ctx):
        if not source_ok:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, {})
        return ToolResult.ok({"total": 3}, {"type": "table", "columns": ["Total"], "rows": [[3]]})

    async def export(params, ctx):
        rendered.append(params)
        if not export_ok:
            return ToolResult(ToolStatus.ERROR, {})
        return ToolResult.ok({}, {"type": "download", "format": "pdf", "url": "/api/reports/" + "a" * 32})

    registry.register(Tool("plantilla", "Consultar", SourceParams, source))
    registry.register(Tool("generar_informe", "Exportar", InformeParams, export))
    actions = iter(
        [
            tool_call(
                "planificar_tarea",
                {
                    "pasos": [
                        {
                            "objetivo": "Consultar",
                            "herramientas": ["plantilla"],
                            "argumentos": {"plantilla": {"departamento": "Cocina"}},
                        },
                        {
                            "objetivo": "Exportar",
                            "herramientas": ["generar_informe"],
                            "depende_de": [0],
                            "argumentos": {
                                "generar_informe": {
                                    "formato": ["pdf"],
                                    "titulo": "Título validado",
                                    "incluir_narrativa": True,
                                }
                            },
                        },
                    ]
                },
            ),
            tool_call("plantilla", {"departamento": "Cocina"}),
        ]
    )
    provider = FakeLLMProvider(lambda request: next(actions, final_answer("Informe pendiente", "Informe pendiente")))
    try:
        result = await ConversationEngine(llm=provider, tools=registry, db=db).complete(
            message="Analiza la plantilla de Cocina y genera PDF", user=CTX.user, session_id=None
        )
        assert result.status == ("ok" if source_ok and export_ok else "error")
        if source_ok:
            assert len(rendered) == 1
            assert rendered[0].titulo == "Título validado" and rendered[0].incluir_narrativa
        else:
            assert not rendered
    finally:
        await db.dispose()


def step(goal, tool, args):
    return {"objetivo": goal, "herramientas": [tool], "argumentos": {tool: args}}


async def propose(plan, steps):
    registry = ToolRegistry()
    registry.register(plan.tool())
    result = await registry.execute(ToolCall("plan", "planificar_tarea", json.dumps({"pasos": steps})), CTX)
    return result.result


@pytest.mark.parametrize("arguments", [{"campo_inventado": "value"}, {"incluir_inactivos": "invalid-boolean"}])
async def test_plan_rejects_unknown_or_invalid_filters_before_acceptance(arguments):
    plan = TaskPlan("Lista la plantilla", frozenset({"plantilla"}), parameter_models={"plantilla": SourceParams})
    result = await propose(plan, [step("Consultar", "plantilla", arguments)])
    assert result.status is ToolStatus.INVALID_ARGUMENTS
    assert plan.steps == [] and plan.revisions == 0


def test_equivalent_report_formats_and_declared_defaults_match_the_real_contract():
    plan = TaskPlan("Genera PDF", frozenset({"generar_informe"}), parameter_models={"generar_informe": InformeParams})
    plan.steps = TaskSteps.model_validate(
        {"pasos": [step("Exportar", "generar_informe", {"formato": ["pdf"], "incluir_detalle": True})]}
    ).pasos
    execution = ToolExecution(
        ToolCall("export", "generar_informe", '{"formato":"pdf"}'),
        ToolResult.ok({}, {"type": "download", "format": "pdf", "url": "/api/reports/" + "a" * 32}),
        1,
        None,
    )
    assert plan.missing([execution]) == []


async def test_replanning_can_replace_an_unsuitable_reporter_without_losing_source_filters():
    models = {
        "plantilla": SourceParams,
        "generar_informe": InformeParams,
        "generar_informe_ejecutivo": InformeEjecutivoParams,
    }
    plan = TaskPlan("Lista Cocina y genera PDF", frozenset(models), parameter_models=models)
    source = step("Consultar", "plantilla", {"departamento": "Cocina"})
    initial = step("Exportar", "generar_informe_ejecutivo", {"departamento": "Cocina", "formato": ["pdf"]})
    assert (await propose(plan, [source, initial])).status is ToolStatus.OK
    corrected = step("Exportar", "generar_informe", {"formato": "pdf"})
    assert (await propose(plan, [source, corrected])).status is ToolStatus.OK
    assert plan.revisions == 2


async def test_replanning_cannot_drop_or_change_the_original_population():
    models = {"generar_informe_ejecutivo": InformeEjecutivoParams, "generar_informe": InformeParams}
    plan = TaskPlan("Genera PDF de Cocina", frozenset(models), parameter_models=models)
    assert (
        await propose(
            plan, [step("Exportar", "generar_informe_ejecutivo", {"departamento": "Cocina", "formato": "pdf"})]
        )
    ).status is ToolStatus.OK
    assert (
        await propose(plan, [step("Exportar", "generar_informe", {"formato": "pdf"})])
    ).status is ToolStatus.INVALID_ARGUMENTS
    assert plan.revisions == 1


async def test_missing_report_options_are_bound_from_the_unique_plan_and_recorded_in_history(tmp_path):
    db = await fresh_database(tmp_path)
    registry = ToolRegistry()
    rendered = []

    async def source(params, ctx):
        return ToolResult.ok(
            {"total": 3}, {"type": "table", "title": "Datos sintéticos", "columns": ["Total"], "rows": [[3]]}
        )

    async def export(params, ctx):
        rendered.append(params)
        return ToolResult.ok({}, {"type": "download", "format": "pdf", "url": "/api/reports/" + "a" * 32})

    registry.register(Tool("plantilla", "Consultar", SourceParams, source))
    registry.register(Tool("generar_informe", "Exportar", InformeParams, export))
    steps = [
        step("Consultar", "plantilla", {"departamento": "Cocina"}),
        step(
            "Exportar",
            "generar_informe",
            {"formato": ["pdf"], "titulo": "Análisis sintético", "incluir_narrativa": True},
        ),
    ]

    def script(request):
        if not any(message.tool_calls for message in request.messages):
            return tool_call("planificar_tarea", {"pasos": steps})
        if not any(m.role == "tool" and '"total": 3' in m.content for m in request.messages):
            return [
                *tool_call("plantilla", {"departamento": "Cocina"}),
                *tool_call("generar_informe", {"formato": "pdf"}, call_id="export"),
            ]
        return final_answer("Informe disponible", "Informe disponible")

    provider = FakeLLMProvider(script)
    try:
        engine = ConversationEngine(llm=provider, tools=registry, db=db, max_tool_rounds=5)
        events = [
            event
            async for event in engine.run(
                message="Analiza la plantilla de Cocina y genera PDF", user=CTX.user, session_id=None
            )
        ]
        result = next(event.result for event in events if isinstance(event, ResultEvent))
        assert result.status == "ok"
        assert len(rendered) == 1 and rendered[0].incluir_narrativa
        assert rendered[0].titulo == "Análisis sintético"
        recorded = [
            call for m in provider.requests[-1].messages for call in m.tool_calls if call.name == "generar_informe"
        ]
        assert json.loads(recorded[-1].arguments)["incluir_narrativa"] is True
    finally:
        await db.dispose()


async def test_plan_never_supplies_missing_confirmation_to_a_write():
    class WriteParams(BaseModel):
        confirmar: bool = False

    called = []

    async def write(params, ctx):
        called.append(True)
        return ToolResult.ok({})

    registry = ToolRegistry()
    registry.register(Tool("enviar_correo", "Enviar", WriteParams, write))
    plan = TaskPlan("Enviar", frozenset({"enviar_correo"}), parameter_models=registry.parameter_models_for(CTX.user))
    assert (await propose(plan, [step("Enviar", "enviar_correo", {"confirmar": True})])).status is ToolStatus.OK
    executions = await plan.execute(registry, [ToolCall("write", "enviar_correo", "{}")], CTX, [], {"enviar_correo"})
    assert executions[0].result.status is ToolStatus.INVALID_ARGUMENTS
    assert called == []


async def test_report_binding_never_chooses_between_two_different_planned_populations():
    plan = TaskPlan(
        "Genera informes",
        frozenset({"generar_informe_ejecutivo"}),
        parameter_models={"generar_informe_ejecutivo": InformeEjecutivoParams},
    )
    assert (
        await propose(
            plan,
            [
                step("Cocina", "generar_informe_ejecutivo", {"departamento": "Cocina", "formato": "pdf"}),
                step("Recepción", "generar_informe_ejecutivo", {"departamento": "Recepción", "formato": "pdf"}),
            ],
        )
    ).status is ToolStatus.OK
    call = ToolCall("export", "generar_informe_ejecutivo", '{"formato":"pdf"}')
    assert not plan.ready(plan._bind_export_call(call), [])
