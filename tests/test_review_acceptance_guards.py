import json
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ConversationEngine, Tool, ToolContext, ToolRegistry
from mia.conversation.argument_contracts import normalize_plan_arguments
from mia.conversation.engine import FinalAnswer
from mia.conversation.events import ResultEvent
from mia.conversation.planning import TaskPlan, TaskSteps, _matching_arguments
from mia.conversation.tools import ToolExecution, ToolResult, ToolStatus
from mia.data import Database, Employee, ShiftDay
from mia.llm import ToolCall
from mia.llm.base import LLMCompleted, TextDelta
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.rrhh import build_rrhh_registry
from mia.modules.rrhh.nominas.analisis_economico import AnalisisEconomicoParams
from mia.modules.rrhh.turnos.tools import TurnosDiaParams
from mia.modules.rrhh.vacaciones.tools import VacacionesParams
from mia.reporting.content_composer import compose_for_request
from mia.reporting.document import Block, Document
from tests.dbutil import fresh_database

NOW = datetime(2026, 10, 31, tzinfo=UTC)
ADMIN = UserContext("synthetic", "Synthetic", roles=frozenset({"mia.admin"}))


@pytest.mark.parametrize("metadata_tool", ["nominas_periodo", "anomalias_nominas"])
async def test_future_payroll_without_source_cannot_be_presented_as_calculated(tmp_path, metadata_tool):
    db = await fresh_database(tmp_path)
    actions = iter(
        [
            tool_call(metadata_tool, {"periodo": "2099-01"}),
            final_answer("Cálculo completado", "He calculado las nóminas"),
        ]
    )
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda request: next(actions)), tools=build_rrhh_registry(db), db=db
        )
        result = await engine.complete(message="Calcula las nóminas de enero de 2099", user=ADMIN, session_id=None)
        assert result.status == "ok"
        assert "No hay nóminas" in result.answer and "2099-01" in result.answer
        assert "No se pueden calcular importes" in result.answer
        assert "Cálculo completado" not in result.answer
    finally:
        await db.dispose()


def test_plan_does_not_freeze_the_wrong_week_as_an_immutable_filter():
    with pytest.raises(ValueError, match="2026-10-26"):
        normalize_plan_arguments(
            VacacionesParams, {"desde": "2026-11-02", "hasta": "2026-11-08"}, "Vacaciones de esta semana", NOW.date()
        )
    assert (
        normalize_plan_arguments(
            VacacionesParams, {"desde": "2026-10-26", "hasta": "2026-11-01"}, "Vacaciones de esta semana", NOW.date()
        )["hasta"]
        == "2026-11-01"
    )


async def test_vacation_read_rejects_another_week_and_defaults_to_the_complete_calendar_week(tmp_path):
    db = await fresh_database(tmp_path)
    try:
        registry = build_rrhh_registry(db)
        ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, user_message="Compara vacaciones de esta semana")
        wrong = await registry.execute(
            ToolCall("bad", "vacaciones", json.dumps({"desde": "2026-11-02", "hasta": "2026-11-08"})), ctx
        )
        assert wrong.result.status is ToolStatus.INVALID_ARGUMENTS
        result = await registry.execute(ToolCall("good", "vacaciones", "{}"), ctx)
        assert result.result.status is ToolStatus.OK
        assert result.result.summary["desde"] == "2026-10-26"
        assert result.result.summary["hasta"] == "2026-11-01"
    finally:
        await db.dispose()


async def test_editor_cannot_drop_the_original_tables_while_selecting_narrative():
    source = Block("table", "Datos", {"columns": ["Grupo", "Coste"], "rows": [["PruebasA", 100]]})
    narrative = Block("narrative", "Análisis", {"statements": []})
    provider = FakeLLMProvider(
        lambda req: [TextDelta(json.dumps({"selected_indices": [1], "unavailable": []})), LLMCompleted()]
    )
    result = await compose_for_request(
        Document("Prueba", [source, narrative]), "Analiza los costes y genera PDF", provider
    )
    assert source in result.blocks and narrative in result.blocks


async def test_verified_source_limitation_cannot_be_replaced_with_a_false_all_clear():
    db = Database("sqlite+aiosqlite:///:memory:")
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda req: final_answer("Listo", "Listo")), tools=ToolRegistry(), db=db
        )
        checked = (
            "No se observan conflictos, pero faltan turnos publicados; no se certifica ausencia de otros conflictos."
        )
        result = ToolResult(ToolStatus.OK, {"limitacion": "Datos incompletos"}, verified_answer=checked)
        turn = SimpleNamespace(
            executions=[ToolExecution(ToolCall("source", "cruce_vacaciones_turnos", "{}"), result, 0, None)], state={}
        )
        answer = engine._verify_candidate(
            FinalAnswer("Todo coordinado", "neutra", "Los turnos y vacaciones están bien coordinados."),
            TaskPlan("Cruza fuentes", frozenset()),
            turn,
            planned=False,
            missing=[],
            pending_steps=[],
        )
        assert answer.text == checked and "bien coordinados" not in answer.text
    finally:
        await db.dispose()


async def test_required_business_verifier_cannot_be_replaced_by_a_generic_source_step():
    request = "Cruza vacaciones y turnos y explica incompatibilidades"
    db = Database("sqlite+aiosqlite:///:memory:")
    try:
        registry = build_rrhh_registry(db)
        required = registry.required_verifiers_for(ADMIN, request)
        assert required == frozenset({"cruce_vacaciones_turnos"})
        restricted = UserContext("restricted", "Restricted", roles=frozenset({"Legal"}))
        assert not registry.required_verifiers_for(restricted, request)
        plan = TaskPlan(request, frozenset(registry.names()), required_verifiers=required)
        ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, user_message=request)
        omitted = TaskSteps.model_validate(
            {"pasos": [{"objetivo": "Consultar plantilla", "herramientas": ["plantilla"]}]}
        )
        assert (await plan.tool().handler(omitted, ctx)).status is ToolStatus.INVALID_ARGUMENTS
        assert plan.steps == []
        unrelated = ToolExecution(ToolCall("source", "plantilla", "{}"), ToolResult.ok({}), 0, None)
        assert any("verificador" in problem for problem in plan.missing([unrelated]))
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    [
        ("septiembre de 2025", "2025-09", True),
        ("2025-09-01 a 2025-09-30", "2025-09", True),
        ("mes pasado", "2026-09", True),
        ("2026-09", "2025-09", False),
        ("2025-09 a 2025-10", "2025-09", False),
    ],
)
def test_period_evidence_uses_domain_dates_without_changing_any_other_filter(actual, expected, matches):
    call = ToolExecution(
        ToolCall("source", "analisis_economico_nominas", json.dumps({"periodo": actual})), ToolResult.ok({}), 0, None
    )
    assert _matching_arguments(call, {"periodo": expected}, AnalisisEconomicoParams, NOW.date()) is matches
    assert not _matching_arguments(
        call, {"periodo": expected, "incluir_inactivos": False}, AnalisisEconomicoParams, NOW.date()
    )


def test_combined_noncontiguous_periods_must_be_separate_tool_calls():
    with pytest.raises(ValueError):
        AnalisisEconomicoParams(periodo="2025-09,2026-09")


def test_native_department_grouping_is_typed_and_does_not_change_period_evidence():
    execution = ToolExecution(
        ToolCall(
            "grouping",
            "analisis_economico_nominas",
            '{"periodo":"2025-09","concepto":"coste_empresa","agrupar_por":"departamento"}',
        ),
        ToolResult.ok({}),
        0,
        None,
    )
    assert _matching_arguments(
        execution, {"periodo": "2025-09", "concepto": "coste_empresa"}, AnalisisEconomicoParams, NOW.date()
    )
    with pytest.raises(ValueError):
        AnalisisEconomicoParams(periodo="2025-09", agrupar_por="persona")


@pytest.mark.parametrize("source_status", [ToolStatus.OK, ToolStatus.SOURCE_UNAVAILABLE])
async def test_omitted_mandatory_read_runs_once_after_a_valid_plan(tmp_path, source_status):
    db = await fresh_database(tmp_path)
    registry = ToolRegistry()
    calls = []

    async def read(params, ctx):
        calls.append(True)
        return ToolResult(source_status, {"total": 2}, verified_answer="Fuente actual: 2 personas trabajando.")

    registry.register(
        Tool(
            "turnos_dia",
            "Lectura actual",
            TurnosDiaParams,
            read,
            verifies_request=lambda message: True,
            verification_arguments=lambda ctx: {},
        )
    )

    def script(request):
        if not any(message.tool_calls for message in request.messages):
            return tool_call(
                "planificar_tarea", {"pasos": [{"objetivo": "Consultar fuente actual", "herramientas": ["turnos_dia"]}]}
            )
        return final_answer("He terminado sin consultar", "He terminado sin consultar")

    try:
        engine = ConversationEngine(llm=FakeLLMProvider(script), tools=registry, db=db)
        events = [
            event
            async for event in engine.run(message="¿Quiénes están trabajando ahora mismo?", user=ADMIN, session_id=None)
        ]
        result = next(event.result for event in events if isinstance(event, ResultEvent))
        assert len(calls) == 1
        assert result.status == ("ok" if source_status is ToolStatus.OK else "error")
        assert "He terminado sin consultar" not in result.answer
    finally:
        await db.dispose()


async def test_simple_current_staff_question_reads_the_real_source_without_requiring_a_model_plan(tmp_path):
    db = await fresh_database(tmp_path)
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()
    async with db.session() as session:
        for index, (active, kind, department) in enumerate(
            [
                (True, "Trabajo", "Cocina"),
                (True, "Trabajo", "Recepción"),
                (False, "Trabajo", "Cocina"),
                (True, "Descanso", "Cocina"),
            ],
            start=1,
        ):
            session.add(
                Employee(
                    sp_id=index,
                    name=f"Synthetic {index}",
                    name_key=f"synthetic {index}",
                    person_key=f"key{index}",
                    active=active,
                    department=department,
                )
            )
            session.add(
                ShiftDay(
                    sp_item_id=index,
                    day=today,
                    person_key=f"key{index}",
                    employee_name=f"Synthetic {index}",
                    department=department,
                    iso_year=today.isocalendar().year,
                    iso_week=today.isocalendar().week,
                    weekday="S",
                    kind=kind,
                    start_time="00:00",
                    end_time="23:59",
                    raw_value="00:00-23:59",
                )
            )
        await session.commit()
    provider = FakeLLMProvider(lambda request: pytest.fail("A native verified lookup needs no model plan"))
    try:
        registry = build_rrhh_registry(db)
        result = await ConversationEngine(llm=provider, tools=registry, db=db).complete(
            message="que empleados estan trabajando ahora mismo?", user=ADMIN, session_id=None
        )
        assert result.status == "ok"
        assert "2 personas trabajando" in result.answer
        assert "Plan explícito pendiente" not in result.answer
        assert [tool["name"] for tool in result.tools] == ["turnos_dia"]
        assert not provider.requests
        ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, user_message="Quién trabaja ahora en Cocina")
        assert not registry.direct_read_calls(ctx)
    finally:
        await db.dispose()


def test_global_current_staff_question_requires_a_fresh_authorized_source():
    db = Database("sqlite+aiosqlite:///:memory:")
    registry = build_rrhh_registry(db)
    assert registry.required_verifiers_for(ADMIN, "¿Qué empleados están trabajando ahora mismo?") == frozenset(
        {"turnos_dia"}
    )
    assert not registry.required_verifiers_for(ADMIN, "¿Quiénes trabajan ahora en Cocina?")


def test_global_now_plan_evidence_uses_the_same_scope_reset_as_the_source():
    call = ToolExecution(ToolCall("now", "turnos_dia", "{}"), ToolResult.ok({}), 0, None)
    assert _matching_arguments(
        call,
        {"fecha": "2026-10-31", "departamento": None, "tipo": "Trabajo"},
        TurnosDiaParams,
        NOW.date(),
        "¿Qué empleados están trabajando ahora mismo?",
    )
    narrowed = ToolExecution(
        ToolCall("scoped", "turnos_dia", json.dumps({"departamento": "Cocina"})), ToolResult.ok({}), 0, None
    )
    assert not _matching_arguments(
        narrowed, {"departamento": None}, TurnosDiaParams, NOW.date(), "Quién trabaja ahora en Cocina"
    )
