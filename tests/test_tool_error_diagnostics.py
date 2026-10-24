"""Fase I — mejora del diagnóstico de errores de herramientas (incidencia trace
mia-20261012-115403-bad97707, Prioridad 5): "para que una futura incidencia permita identificar la
excepción interna sin exponer información sensible."

Antes de esta mejora, una excepción real dentro de una herramienta solo llegaba a `log.exception`
(servidor) — la traza de diagnóstico (lo que vería un panel/incidencia) solo tenía
`{"tool": ..., "status": "error"}`, sin ningún dato para localizar la excepción sin reproducirla a
ciegas. Ahora incluye también el TIPO de excepción y su ubicación (archivo:línea DENTRO de
``src/mia/``) — nunca el mensaje de la excepción ni ningún argumento, que podrían contener datos
sensibles (importes, nombres…)."""

from __future__ import annotations

from pydantic import BaseModel

from mia.auth import UserContext
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.diagnostics import EventStage
from mia.diagnostics.trace import begin_trace
from mia.diagnostics.store import DiagnosticsStore
from mia.diagnostics.streaming import LiveBroadcaster
from mia.llm import ToolCall
from mia.settings import DiagnosticsSettings

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))

_SENSITIVE_MESSAGE = "importe real 12.345,67 € para Ana López — nunca debe aparecer en la traza"


class _NoParams(BaseModel):
    pass


def _crashing_tool() -> Tool:
    async def handler(_p: _NoParams, _ctx: ToolContext) -> ToolResult:
        raise ValueError(_SENSITIVE_MESSAGE)

    return Tool("herramienta_que_falla", "Para pruebas: siempre lanza una excepción real.", _NoParams, handler)


async def test_tool_exception_is_diagnosable_without_leaking_its_message() -> None:
    registry = ToolRegistry()
    registry.register(_crashing_tool())
    ctx = ToolContext(user=ADMIN, request_id=None, now=None, session_state={})  # type: ignore[arg-type]

    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    async with begin_trace(query="prueba", user_id="u", store=store, broadcaster=broadcaster) as trace:
        assert trace is not None
        execution = await registry.execute(ToolCall("c1", "herramienta_que_falla", "{}"), ctx)

    assert execution.result.status is ToolStatus.ERROR
    # El mensaje que vería el usuario/LLM sigue siendo el genérico de siempre — nunca la excepción real.
    assert _SENSITIVE_MESSAGE not in str(execution.result.summary)

    saved = store.get(trace.trace_id)
    assert saved is not None
    error_events = [e for e in saved.events if e.stage == EventStage.TOOL_CALL_ERROR]
    assert len(error_events) == 1, "debe haber exactamente un evento TOOL_CALL_ERROR, nunca duplicado"
    event = error_events[0]

    assert event.data["exception_type"] == "ValueError"
    assert event.data["exception_location"] is not None
    assert "test_tool_error_diagnostics.py" in event.data["exception_location"] or "tools.py" in event.data["exception_location"]

    # Nunca el mensaje real, en ningún campo del evento.
    serialized = str(event.data)
    assert _SENSITIVE_MESSAGE not in serialized
    assert "Ana López" not in serialized
    assert "12.345,67" not in serialized


async def test_semantic_search_tools_report_tool_call_error_when_llm_unavailable(tmp_path) -> None:
    """``buscar_en_nominas``/``buscar_en_documentos`` (indexación de contenido sensible, ver
    mia.modules.rrhh.document_indexing) ya devuelven SOURCE_UNAVAILABLE sin excepción cuando
    ``deps.llm is None`` — confirma que ``ToolRegistry.execute()`` lo sigue tratando como
    TOOL_CALL_ERROR (is_error incluye "source_unavailable") sin necesidad de cambios ahí, y que el
    nuevo evento RAG_SEARCH_ERROR específico del dominio también se emite."""
    import json
    from types import SimpleNamespace

    from mia.data import Database
    from mia.diagnostics import EventStage as DiagStage
    from mia.modules.registry import build_registry
    from tests.dbutil import fresh_database

    db: Database = await fresh_database(tmp_path, "rag_llm_unavailable.db")
    settings = SimpleNamespace(
        data=SimpleNamespace(index_sensitive_content=True, content_enabled=True),
        curriculums=SimpleNamespace(embedding_model="x"),
    )
    registry = build_registry(db, settings=settings, llm=None)
    ctx = ToolContext(user=ADMIN, request_id=None, now=None, session_state={})  # type: ignore[arg-type]

    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    for tool_name, args in (
        ("buscar_en_nominas", {"consulta": "dietas"}),
        ("buscar_en_documentos", {"consulta": "vacaciones"}),
    ):
        async with begin_trace(query="prueba", user_id="u", store=store, broadcaster=broadcaster) as trace:
            assert trace is not None
            execution = await registry.execute(ToolCall("c1", tool_name, json.dumps(args)), ctx)
        assert execution.result.status is ToolStatus.SOURCE_UNAVAILABLE

        saved = store.get(trace.trace_id)
        assert saved is not None
        error_events = [e for e in saved.events if e.stage == EventStage.TOOL_CALL_ERROR]
        assert len(error_events) == 1, f"{tool_name}: debe reportarse como TOOL_CALL_ERROR"
        rag_error_events = [e for e in saved.events if e.stage == DiagStage.RAG_SEARCH_ERROR]
        assert len(rag_error_events) == 1, f"{tool_name}: debe emitir RAG_SEARCH_ERROR"
        assert rag_error_events[0].data.get("motivo") == "llm_no_configurado"

    await db.dispose()


async def test_a_clean_tool_result_still_emits_exactly_one_complete_event() -> None:
    """Confirma que la instrumentación nueva no duplica eventos para el camino normal (sin excepción)."""

    class _OkTool:
        pass

    async def handler(_p: _NoParams, _ctx: ToolContext) -> ToolResult:
        return ToolResult(ToolStatus.OK, {"mensaje": "todo bien"})

    registry = ToolRegistry()
    registry.register(Tool("herramienta_ok", "Para pruebas.", _NoParams, handler))
    ctx = ToolContext(user=ADMIN, request_id=None, now=None, session_state={})  # type: ignore[arg-type]

    store = DiagnosticsStore(DiagnosticsSettings(enabled=True))
    broadcaster = LiveBroadcaster()
    async with begin_trace(query="prueba", user_id="u", store=store, broadcaster=broadcaster) as trace:
        assert trace is not None
        await registry.execute(ToolCall("c1", "herramienta_ok", "{}"), ctx)

    saved = store.get(trace.trace_id)
    assert saved is not None
    complete_events = [e for e in saved.events if e.stage == EventStage.TOOL_CALL_COMPLETE]
    error_events = [e for e in saved.events if e.stage == EventStage.TOOL_CALL_ERROR]
    assert len(complete_events) == 1
    assert len(error_events) == 0
    assert "exception_type" not in complete_events[0].data
