"""El usuario final nunca debe ver jerga interna de planificación ("paso 2: ..."):
la respuesta final debe distinguir fallo de fuente, insuficiencia de datos, aclaración
necesaria y verificación/objetivo pendiente en frases comprensibles (encargo: capacidad 1,
orquestador inteligente)."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import ConversationEngine, Tool, ToolContext, ToolRegistry
from mia.conversation.engine import FinalAnswer, _direct_read_failure_detail
from mia.conversation.planning import (
    IncompleteReason,
    TaskPlan,
    TaskSteps,
    compose_incomplete_message,
    incomplete_detail_lines,
)
from mia.conversation.tools import ToolExecution, ToolResult, ToolStatus
from mia.data import Database
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer
from tests.dbutil import fresh_database


def execution(name: str, status: ToolStatus = ToolStatus.OK) -> ToolExecution:
    return ToolExecution(ToolCall(name, name, "{}"), ToolResult(status, {}), 0, None)


def single_step_plan(tool: str) -> TaskPlan:
    plan = TaskPlan("Consulta", frozenset({tool}))
    plan.steps = TaskSteps.model_validate(
        {"pasos": [{"objetivo": "Consultar la fuente", "herramientas": [tool]}]}
    ).pasos
    return plan


def test_source_failure_is_reported_in_plain_language_without_internal_jargon():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla", ToolStatus.SOURCE_UNAVAILABLE)])
    assert len(steps) == 1
    assert steps[0].reason is IncompleteReason.FUENTE_NO_DISPONIBLE
    message = compose_incomplete_message(steps)
    assert "no respondió" in message or "falló" in message
    assert "paso " not in message
    assert "source_unavailable" not in message


def test_permission_denied_is_distinguished_from_source_failure():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla", ToolStatus.PERMISSION_DENIED)])
    assert steps[0].reason is IncompleteReason.PERMISO_DENEGADO
    assert "permiso" in compose_incomplete_message(steps)


def test_ambiguous_result_asks_for_clarification():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla", ToolStatus.AMBIGUOUS)])
    assert steps[0].reason is IncompleteReason.ACLARACION_NECESARIA
    assert "aclar" in compose_incomplete_message(steps)


def test_invalid_arguments_also_asks_for_clarification_not_a_raw_status_code():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla", ToolStatus.INVALID_ARGUMENTS)])
    assert steps[0].reason is IncompleteReason.ACLARACION_NECESARIA
    assert "invalid_arguments" not in compose_incomplete_message(steps)


def test_not_found_is_reported_as_insufficient_data():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla", ToolStatus.NOT_FOUND)])
    assert steps[0].reason is IncompleteReason.DATOS_INSUFICIENTES
    assert "datos" in compose_incomplete_message(steps)


def test_step_never_attempted_is_pending_execution_not_mistaken_for_a_source_failure():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([])
    assert steps[0].reason is IncompleteReason.EJECUCION_PENDIENTE


def test_unmet_dependency_blocks_the_dependent_step_as_pending_not_as_a_failure():
    plan = TaskPlan("Compara", frozenset({"leer", "analizar"}))
    plan.steps = TaskSteps.model_validate(
        {
            "pasos": [
                {"objetivo": "Consultar origen", "herramientas": ["leer"]},
                {"objetivo": "Comparar resultado", "herramientas": ["analizar"], "depende_de": [0]},
            ]
        }
    ).pasos
    steps = plan.incomplete_steps([execution("leer", ToolStatus.SOURCE_UNAVAILABLE)])
    by_objective = {s.objetivo: s for s in steps}
    assert by_objective["Consultar origen"].reason is IncompleteReason.FUENTE_NO_DISPONIBLE
    assert by_objective["Comparar resultado"].reason is IncompleteReason.EJECUCION_PENDIENTE


def test_required_verifier_missing_is_reported_as_verification_pending():
    plan = TaskPlan("Consulta", frozenset({"plantilla"}), required_verifiers=frozenset({"turnos_dia"}))
    steps = plan.incomplete_steps([execution("plantilla")])
    assert any(s.reason is IncompleteReason.VERIFICACION_PENDIENTE for s in steps)
    message = compose_incomplete_message(steps)
    assert "verificador" not in message.lower()


def test_fully_completed_plan_has_no_incomplete_steps():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla")])
    assert steps == []
    assert compose_incomplete_message(steps) == ""


def test_permission_denied_outranks_a_concurrent_source_failure_in_the_same_step():
    plan = TaskPlan("Consulta", frozenset({"a", "b"}))
    plan.steps = TaskSteps.model_validate(
        {"pasos": [{"objetivo": "Consultar ambas", "herramientas": ["a", "b"]}]}
    ).pasos
    steps = plan.incomplete_steps(
        [execution("a", ToolStatus.SOURCE_UNAVAILABLE), execution("b", ToolStatus.PERMISSION_DENIED)]
    )
    assert steps[0].reason is IncompleteReason.PERMISO_DENEGADO


def test_detail_lines_name_the_objective_not_a_step_index():
    plan = single_step_plan("plantilla")
    steps = plan.incomplete_steps([execution("plantilla", ToolStatus.SOURCE_UNAVAILABLE)])
    lines = incomplete_detail_lines(steps)
    assert lines == ["- «Consultar la fuente»: la fuente de datos no respondió o falló al consultarla."]


async def test_engine_verify_candidate_shows_the_real_reason_not_the_raw_planner_label():
    """End-to-end through the actual leak point (engine.py's _verify_candidate), not just the
    isolated TaskPlan helper: this is what the user would actually see on screen."""
    db = Database("sqlite+aiosqlite:///:memory:")
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda req: final_answer("No importa", "No importa")), tools=ToolRegistry(), db=db
        )
        plan = single_step_plan("plantilla")
        executions = [execution("plantilla", ToolStatus.SOURCE_UNAVAILABLE)]
        turn = SimpleNamespace(executions=executions, state={})
        missing = plan.missing(executions)
        pending_steps = [item for item in missing if item.startswith("paso ")]
        assert pending_steps, "la fijación del escenario debe dejar el plan incompleto"
        answer = engine._verify_candidate(
            FinalAnswer("habla", "neutra", "texto"),
            plan,
            turn,
            planned=True,
            missing=missing,
            pending_steps=pending_steps,
        )
        assert "paso " not in answer.text
        assert "sin evidencia de ejecución completa" not in answer.text
        assert "Consultar la fuente" in answer.text
        assert "no respondió" in answer.text or "falló" in answer.text
    finally:
        await db.dispose()


async def test_engine_handles_an_accepted_plan_with_zero_steps_without_losing_the_signal():
    """Edge case: a plan was accepted (planned=True) but declared no steps at all. incomplete_steps()
    has nothing to iterate, so _verify_candidate must still say something, not silently empty out."""
    db = Database("sqlite+aiosqlite:///:memory:")
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda req: final_answer("No importa", "No importa")), tools=ToolRegistry(), db=db
        )
        plan = TaskPlan("Consulta", frozenset())
        turn = SimpleNamespace(executions=[], state={})
        answer = engine._verify_candidate(
            FinalAnswer("habla", "neutra", "texto"),
            plan,
            turn,
            planned=True,
            missing=["Plan explícito pendiente; no se ha verificado la tarea."],
            pending_steps=["Plan explícito pendiente; no se ha verificado la tarea."],
        )
        assert answer.text
        assert "paso " not in answer.text
    finally:
        await db.dispose()


async def test_direct_read_failure_shows_the_tools_own_specific_message_not_a_generic_one(tmp_path):
    """Real incident found live (candidato21, caso E05): un grupo de 1 persona hace que
    comparativa_salarial rechace correctamente mostrar su salario (proteccion k-anonimato,
    MIN_GROUP) con un mensaje especifico en result.summary['mensaje'] - pero el recorrido de
    lectura directa lo descartaba y mostraba siempre el mismo texto generico, sin importar la
    causa real. No es un fallo del orquestador: es exactamente la misma jerga/indiferenciacion
    que la capacidad 1 pide evitar, en una ruta distinta a la ya corregida."""

    class Params(BaseModel):
        pass

    specific_message = "El grupo tiene menos de 3 personas: no se muestran importes individuales (protección de datos)."

    async def handler(p: Params, ctx: ToolContext) -> ToolResult:
        return ToolResult(ToolStatus.PERMISSION_DENIED, {"mensaje": specific_message, "personas_del_grupo": 1})

    registry = ToolRegistry()
    registry.register(
        Tool(
            "comparativa_salarial",
            "Comparativa salarial",
            Params,
            handler,
            direct_read_arguments=lambda ctx: {},
        )
    )
    db = await fresh_database(tmp_path)
    try:
        engine = ConversationEngine(
            llm=FakeLLMProvider(lambda req: final_answer("no debería llamarse", "no debería llamarse")),
            tools=registry,
            db=db,
        )
        result = await engine.complete(
            message="Compara el salario de esas personas en agosto de 2026",
            user=UserContext("synthetic", "Synthetic"),
            session_id=None,
        )
        assert result.answer == specific_message
        assert "No he podido completar la lectura de la fuente autorizada" not in result.answer
    finally:
        await db.dispose()


def test_direct_read_failure_detail_falls_back_to_a_plain_message_when_the_tool_gives_nothing_usable():
    assert _direct_read_failure_detail(ToolResult(ToolStatus.ERROR, None)) == "No se ha completado la lectura autorizada."
    assert _direct_read_failure_detail(ToolResult(ToolStatus.ERROR, {})) == "No se ha completado la lectura autorizada."
    assert _direct_read_failure_detail(ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "El buzón no está configurado")) == (
        "El buzón no está configurado"
    )
