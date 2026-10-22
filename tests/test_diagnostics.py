"""Tests del módulo de diagnóstico (mia.diagnostics).

Cobertura mínima del spec (punto 57):
- diagnostics disabled (overhead=0, no data stored)
- diagnostics enabled (trace creation, event registration)
- trace creation
- event registration
- redaction
- storage
- streaming
- trace completion
- tool failure tracking
- diagnostics internal failure does not break pipeline
- label/golden dataset
- metrics computation
- analyzer assessment
- noop begin_trace when disabled
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _make_store(max_traces: int = 100, retention_hours: int = 24):
    from mia.diagnostics.config import DiagnosticsSettings
    from mia.diagnostics.store import DiagnosticsStore
    return DiagnosticsStore(DiagnosticsSettings(enabled=True, max_traces=max_traces, retention_hours=retention_hours))


def _make_broadcaster():
    from mia.diagnostics.streaming import LiveBroadcaster
    return LiveBroadcaster()


def _make_trace(query: str = "test query"):
    from mia.diagnostics.models import TraceRecord
    from mia.diagnostics.trace import new_trace_id
    return TraceRecord(
        trace_id=new_trace_id(),
        started_at=datetime.now(UTC),
        query=query,
    )


# ── DISABLED MODE ─────────────────────────────────────────────────────────────

def test_disabled_is_enabled_returns_false():
    """Con MIA_DIAGNOSTICS__ENABLED=false, is_enabled() debe ser False."""
    import mia.diagnostics as d
    # Reseteamos singletons para test aislado
    original_store = d._store
    d._store = None
    try:
        assert d.is_enabled() is False
    finally:
        d._store = original_store


def test_disabled_emit_is_noop():
    """emit() no lanza cuando no hay traza activa."""
    from mia.diagnostics import emit, EventStage
    emit(EventStage.REQUEST_RECEIVED, data={"test": True})  # no debe lanzar


def test_disabled_current_trace_returns_none():
    """current_trace() devuelve None cuando no hay traza en el contextvar."""
    from mia.diagnostics import current_trace
    assert current_trace() is None


@pytest.mark.asyncio
async def test_disabled_begin_trace_yields_none():
    """begin_trace() cuando disabled (no store) debe yield None sin errores."""
    import mia.diagnostics as d
    original_store = d._store
    original_broadcaster = d._broadcaster
    d._store = None
    d._broadcaster = None
    try:
        async with d.begin_trace(query="hola") as trace:
            assert trace is None
    finally:
        d._store = original_store
        d._broadcaster = original_broadcaster


# ── TRACE CREATION ────────────────────────────────────────────────────────────

def test_new_trace_id_format():
    from mia.diagnostics.trace import new_trace_id
    tid = new_trace_id()
    assert tid.startswith("mia-")
    assert len(tid) > 20


def test_trace_record_initial_state():
    record = _make_trace("¿Cómo va Cocina?")
    assert record.status == "running"
    assert record.query == "¿Cómo va Cocina?"
    assert record.events == []
    assert record.tools_called == []
    assert record.error_count == 0


# ── EVENT REGISTRATION ────────────────────────────────────────────────────────

def test_trace_context_emit_adds_event():
    from mia.diagnostics.models import EventStage
    from mia.diagnostics.trace import TraceContext
    store = _make_store()
    broadcaster = _make_broadcaster()
    record = _make_trace()
    ctx = TraceContext(record, store, broadcaster)
    ctx.emit(EventStage.REQUEST_RECEIVED, data={"query": "test"})
    assert len(record.events) == 1
    assert record.events[0].stage == EventStage.REQUEST_RECEIVED


def test_trace_context_emit_never_raises_on_bad_data():
    from mia.diagnostics.trace import TraceContext
    store = _make_store()
    broadcaster = _make_broadcaster()
    record = _make_trace()
    ctx = TraceContext(record, store, broadcaster)
    # Objetos no serializables → no debe lanzar
    ctx.emit("SOME_STAGE", data={"obj": object()})  # no lanza


def test_trace_context_domain_detection_updates_summary():
    from mia.diagnostics.models import EventStage
    from mia.diagnostics.trace import TraceContext
    store = _make_store()
    record = _make_trace()
    ctx = TraceContext(record, store, _make_broadcaster())
    ctx.emit(EventStage.DOMAIN_DETECTION, data={"modules": ["rrhh"]})
    assert "rrhh" in record.modules
    assert record.domain is not None


def test_trace_context_tool_call_updates_tools_list():
    from mia.diagnostics.models import EventStage
    from mia.diagnostics.trace import TraceContext
    store = _make_store()
    record = _make_trace()
    ctx = TraceContext(record, store, _make_broadcaster())
    ctx.emit(EventStage.TOOL_CALL_START, data={"tool": "empleados"})
    assert "empleados" in record.tools_called


def test_trace_context_llm_response_updates_token_counts():
    from mia.diagnostics.models import EventStage
    from mia.diagnostics.trace import TraceContext
    store = _make_store()
    record = _make_trace()
    ctx = TraceContext(record, store, _make_broadcaster())
    ctx.emit(EventStage.LLM_RESPONSE, data={"input_tokens": 100, "output_tokens": 50, "cached_tokens": 20})
    assert record.tokens_input == 100
    assert record.tokens_output == 50
    assert record.tokens_cached == 20


# ── REDACTION ─────────────────────────────────────────────────────────────────

def test_redact_removes_api_key():
    from mia.diagnostics.sanitizer import redact
    data = {"api_key": "sk-abcdef12345", "query": "test"}
    result = redact(data)
    assert result["api_key"] == "***REDACTED***"
    assert result["query"] == "test"


def test_redact_removes_password_nested():
    from mia.diagnostics.sanitizer import redact
    data = {"db": {"password": "secret123", "host": "localhost"}}
    result = redact(data)
    assert result["db"]["password"] == "***REDACTED***"
    assert result["db"]["host"] == "localhost"


def test_redact_mask_pii_when_enabled():
    from mia.diagnostics.sanitizer import redact
    data = {"nombre": "Juan García", "salario": 30000}
    result = redact(data, mask_pii=True)
    assert result["nombre"] == "***"
    assert result["salario"] == 30000


def test_redact_no_pii_mask_when_disabled():
    from mia.diagnostics.sanitizer import redact
    data = {"nombre": "Juan García"}
    result = redact(data, mask_pii=False)
    assert result["nombre"] == "Juan García"


# ── STORAGE ───────────────────────────────────────────────────────────────────

def test_store_put_and_get():
    store = _make_store()
    record = _make_trace("consulta")
    store.put(record)
    assert store.get(record.trace_id) is record


def test_store_get_missing_returns_none():
    store = _make_store()
    assert store.get("no-existe") is None


def test_store_evicts_oldest_when_full():
    store = _make_store(max_traces=2)
    r1 = _make_trace("q1")
    r2 = _make_trace("q2")
    r3 = _make_trace("q3")
    store.put(r1)
    store.put(r2)
    store.put(r3)
    assert store.get(r1.trace_id) is None  # expulsado
    assert store.get(r3.trace_id) is r3


def test_store_list_returns_most_recent_first():
    import time as _time
    from datetime import timedelta
    store = _make_store()
    r1 = _make_trace("old")
    r1.started_at = datetime.now(UTC) - timedelta(seconds=10)
    r2 = _make_trace("new")
    store.put(r1)
    store.put(r2)
    listed = store.list()
    assert listed[0].trace_id == r2.trace_id


def test_store_label_updates_record():
    store = _make_store()
    record = _make_trace()
    store.put(record)
    result = store.label(record.trace_id, "correct", "Looks good")
    assert result is True
    assert record.label == "correct"
    assert record.developer_notes == "Looks good"


def test_store_label_missing_trace_returns_false():
    store = _make_store()
    assert store.label("no-existe", "correct") is False


# ── STREAMING ─────────────────────────────────────────────────────────────────

def test_broadcaster_subscribe_and_publish():
    broadcaster = _make_broadcaster()
    q = broadcaster.subscribe()
    broadcaster.publish({"type": "test", "data": "hello"})
    assert not q.empty()
    item = q.get_nowait()
    assert item["type"] == "test"


def test_broadcaster_unsubscribe_removes_queue():
    broadcaster = _make_broadcaster()
    q = broadcaster.subscribe()
    assert broadcaster.subscriber_count() == 1
    broadcaster.unsubscribe(q)
    assert broadcaster.subscriber_count() == 0


# ── TRACE COMPLETION ──────────────────────────────────────────────────────────

def test_trace_finish_sets_completed_status():
    from mia.diagnostics.models import TraceStatus
    from mia.diagnostics.trace import TraceContext
    store = _make_store()
    record = _make_trace()
    ctx = TraceContext(record, store, _make_broadcaster())
    ctx.finish(answer="La respuesta", status=TraceStatus.COMPLETED)
    assert record.status == TraceStatus.COMPLETED
    assert record.completed_at is not None
    assert record.elapsed_ms is not None
    assert record.final_answer == "La respuesta"


# ── ANALYZER ─────────────────────────────────────────────────────────────────

def test_analyzer_detects_performance_warning():
    from mia.diagnostics.analyzer import analyze
    record = _make_trace()
    record.elapsed_ms = 15_000
    record.status = "completed"
    analyze(record)
    types = [i.type for i in record.issues]
    assert "PERFORMANCE_WARNING" in types


def test_analyzer_detects_tool_error():
    from mia.diagnostics.analyzer import analyze
    record = _make_trace()
    record.tool_errors = 2
    record.status = "completed"
    analyze(record)
    types = [i.type for i in record.issues]
    assert "TOOL_ERROR" in types


def test_analyzer_no_false_positive_on_clean_trace():
    from mia.diagnostics.analyzer import analyze
    record = _make_trace()
    record.elapsed_ms = 1000
    record.status = "completed"
    record.tool_errors = 0
    record.tools_called = ["empleados"]
    analyze(record)
    assert record.issues == []


# ── METRICS ───────────────────────────────────────────────────────────────────

def test_metrics_empty_input():
    from mia.diagnostics.metrics import compute_metrics
    m = compute_metrics([])
    assert m["total_requests"] == 0
    assert m["error_rate"] == 0.0


def test_metrics_computes_error_rate():
    from mia.diagnostics.metrics import compute_metrics
    r1 = _make_trace()
    r1.status = "completed"
    r2 = _make_trace()
    r2.status = "error"
    m = compute_metrics([r1, r2])
    assert m["total_requests"] == 2
    assert m["errors"] == 1
    assert abs(m["error_rate"] - 0.5) < 0.01


def test_metrics_computes_cache_hit_rate():
    from mia.diagnostics.metrics import compute_metrics
    r1 = _make_trace()
    r1.status = "completed"
    r1.tokens_input = 100
    r1.tokens_cached = 80
    r2 = _make_trace()
    r2.status = "completed"
    r2.tokens_input = 100
    r2.tokens_cached = 20
    m = compute_metrics([r1, r2])
    assert m["total_input_tokens"] == 200
    assert m["total_cached_tokens"] == 100
    assert abs(m["cache_hit_rate"] - 0.5) < 0.01


def test_metrics_cache_hit_rate_none_without_input_tokens():
    from mia.diagnostics.metrics import compute_metrics
    r1 = _make_trace()
    r1.status = "completed"
    m = compute_metrics([r1])
    assert m["cache_hit_rate"] is None


# ── PHASE 2: TEMPORAL CONSTRAINT DETECTION ───────────────────────────────────

def test_temporal_constraint_dropped_detected():
    """Detecta TEMPORAL_CONSTRAINT_DROPPED cuando el usuario dice 'ahora' y no se pasa hora."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from mia.diagnostics.trace import new_trace_id
    from datetime import UTC, datetime

    record = _make_trace("quien esta trabajando ahora en restaurante")
    record.now_local = "2026-10-07T21:55:00+02:00"
    record.status = "completed"
    event = DiagnosticEvent(
        trace_id=record.trace_id,
        timestamp=datetime.now(UTC),
        stage=EventStage.TOOL_CALL_START,
        data={"tool": "turnos_dia", "args": {"fecha": "2026-10-07", "departamento": "Restaurante"}},
    )
    record.events.append(event)
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED in types


def test_temporal_constraint_not_flagged_when_hora_present():
    """No debe marcarse si el LLM pasó 'hora' correctamente."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("quien esta trabajando ahora en restaurante")
    record.status = "completed"
    event = DiagnosticEvent(
        trace_id=record.trace_id,
        timestamp=datetime.now(UTC),
        stage=EventStage.TOOL_CALL_START,
        data={"tool": "turnos_dia", "args": {"fecha": "2026-10-07", "hora": "21:55", "departamento": "Restaurante"}},
    )
    record.events.append(event)
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED not in types


def test_temporal_constraint_not_flagged_without_temporal_query():
    """No debe marcarse para consultas sin lenguaje temporal de 'ahora'."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("quien trabaja el lunes en restaurante")
    record.status = "completed"
    event = DiagnosticEvent(
        trace_id=record.trace_id,
        timestamp=datetime.now(UTC),
        stage=EventStage.TOOL_CALL_START,
        data={"tool": "turnos_dia", "args": {"fecha": "2026-10-12", "departamento": "Restaurante"}},
    )
    record.events.append(event)
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED not in types


def test_temporal_constraint_not_flagged_for_non_temporal_tools():
    """No debe marcarse para herramientas que no requieren filtro de hora."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("cuantos empleados hay ahora")
    record.status = "completed"
    event = DiagnosticEvent(
        trace_id=record.trace_id,
        timestamp=datetime.now(UTC),
        stage=EventStage.TOOL_CALL_START,
        data={"tool": "empleados", "args": {}},
    )
    record.events.append(event)
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED not in types


def test_call_graph_node_added_to_trace():
    """add_call_graph_node() debe añadir nodos al call_graph de TraceRecord."""
    from mia.diagnostics.trace import TraceContext

    store = _make_store()
    record = _make_trace()
    ctx = TraceContext(record, store, _make_broadcaster())
    ctx.add_call_graph_node({
        "id": "tool:turnos_dia:call-001",
        "kind": "tool_call",
        "label": "turnos_dia(fecha=2026-10-07)",
        "status": "ok",
        "duration_ms": 42,
        "parent_id": "engine:root",
    })
    assert len(record.call_graph) == 1
    assert record.call_graph[0]["id"] == "tool:turnos_dia:call-001"


def test_call_graph_node_never_raises():
    """add_call_graph_node() no debe lanzar si se pasan datos problemáticos."""
    from mia.diagnostics.trace import TraceContext

    store = _make_store()
    record = _make_trace()
    ctx = TraceContext(record, store, _make_broadcaster())
    ctx.add_call_graph_node({"id": "test", "bad_obj": object()})  # no lanza


def test_now_local_field_exists_in_trace_record():
    """TraceRecord debe tener campo now_local."""
    from mia.diagnostics.models import TraceRecord
    from mia.diagnostics.trace import new_trace_id
    from datetime import UTC, datetime

    record = TraceRecord(
        trace_id=new_trace_id(),
        started_at=datetime.now(UTC),
        query="test",
        now_local="2026-10-07T21:55:00+02:00",
    )
    assert record.now_local == "2026-10-07T21:55:00+02:00"
    d = record.to_dict()
    assert d["now_local"] == "2026-10-07T21:55:00+02:00"
    assert "call_graph" in d


def test_temporal_constraint_issue_includes_now_local_in_details():
    """El issue TEMPORAL_CONSTRAINT_DROPPED debe incluir now_local en details."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("quien trabaja ahora")
    record.now_local = "2026-10-07T21:55:00+02:00"
    record.status = "completed"
    event = DiagnosticEvent(
        trace_id=record.trace_id,
        timestamp=datetime.now(UTC),
        stage=EventStage.TOOL_CALL_START,
        data={"tool": "turnos_dia", "args": {"fecha": "2026-10-07"}},
    )
    record.events.append(event)
    analyze(record)
    temporal_issues = [i for i in record.issues if i.type == DiagnosticIssueType.TEMPORAL_CONSTRAINT_DROPPED]
    assert temporal_issues
    assert temporal_issues[0].details.get("now_local") == "2026-10-07T21:55:00+02:00"


def test_assess_includes_semantic_analysis():
    """assess() debe incluir semantic_analysis cuando hay TEMPORAL_CONSTRAINT_DROPPED."""
    from mia.diagnostics.analyzer import assess
    from mia.diagnostics.models import EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("quien trabaja ahora en cocina")
    record.now_local = "2026-10-07T21:55:00+02:00"
    record.status = "completed"
    event = DiagnosticEvent(
        trace_id=record.trace_id,
        timestamp=datetime.now(UTC),
        stage=EventStage.TOOL_CALL_START,
        data={"tool": "turnos_dia", "args": {"fecha": "2026-10-07", "departamento": "Cocina"}},
    )
    record.events.append(event)
    result = assess(record)
    assert result["temporal_constraint_dropped"] is True
    assert result["semantic_analysis"] is not None
    sa = result["semantic_analysis"]
    assert sa["actual_tool"] == "turnos_dia"
    assert sa["missing_constraint"] == "hora"
    assert sa["possible_root_cause"] == "TEMPORAL_CONSTRAINT_DROPPED"


def test_current_call_id_default_none():
    """current_call_id() debe devolver None cuando no hay call activo."""
    from mia.diagnostics import current_call_id
    assert current_call_id() is None


# ── BEGIN_TRACE CONTEXT MANAGER (ENABLED) ────────────────────────────────────

@pytest.mark.asyncio
async def test_begin_trace_enabled_creates_context():
    """begin_trace() con store activo debe crear y devolver un TraceContext."""
    import mia.diagnostics as d
    store = _make_store()
    broadcaster = _make_broadcaster()
    d.setup(store, broadcaster)
    try:
        async with d.begin_trace(query="¿Cuántos empleados hay?", user_id="user1") as trace:
            assert trace is not None
            assert trace.trace_id.startswith("mia-")
            d.emit(d.EventStage.REQUEST_RECEIVED, data={"q": "test"})
            assert len(trace.record.events) > 0
    finally:
        # Limpieza: reseteamos para no afectar otros tests
        d._store = None
        d._broadcaster = None


@pytest.mark.asyncio
async def test_begin_trace_contextvar_is_set_and_reset():
    """El ContextVar debe estar activo dentro del bloque y None fuera."""
    import mia.diagnostics as d
    store = _make_store()
    broadcaster = _make_broadcaster()
    d.setup(store, broadcaster)
    try:
        assert d.current_trace() is None
        async with d.begin_trace(query="test") as trace:
            assert d.current_trace() is trace
        assert d.current_trace() is None
    finally:
        d._store = None
        d._broadcaster = None


@pytest.mark.asyncio
async def test_begin_trace_internal_exception_does_not_swallow_original():
    """Errores DENTRO del bloque deben propagarse aunque el trace falle."""
    import mia.diagnostics as d
    store = _make_store()
    broadcaster = _make_broadcaster()
    d.setup(store, broadcaster)
    try:
        with pytest.raises(ValueError, match="error de negocio"):
            async with d.begin_trace(query="test"):
                raise ValueError("error de negocio")
    finally:
        d._store = None
        d._broadcaster = None


# ── PHASE 3: RAG / BÚSQUEDA SEMÁNTICA ────────────────────────────────────────

def test_rag_no_results_detected():
    """RAG_SEARCH_COMPLETE con hits=0 debe marcar RAG_NO_RESULTS."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("busca en las nominas algo sobre dietas")
    record.status = "completed"
    record.events.append(
        DiagnosticEvent(
            trace_id=record.trace_id,
            timestamp=datetime.now(UTC),
            stage=EventStage.RAG_SEARCH_COMPLETE,
            data={"dominio": "nominas", "hits": 0, "top_score": None},
        )
    )
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.RAG_NO_RESULTS in types


def test_rag_no_results_not_flagged_when_hits_present():
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("busca en las nominas algo sobre dietas")
    record.status = "completed"
    record.events.append(
        DiagnosticEvent(
            trace_id=record.trace_id,
            timestamp=datetime.now(UTC),
            stage=EventStage.RAG_SEARCH_COMPLETE,
            data={"dominio": "nominas", "hits": 3, "top_score": 0.8},
        )
    )
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.RAG_NO_RESULTS not in types


def test_rag_low_confidence_detected_below_threshold():
    """RAG_SEARCH_COMPLETE con hits>0 pero top_score por debajo del umbral debe marcar RAG_LOW_CONFIDENCE."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("busca en los documentos algo sobre vacaciones")
    record.status = "completed"
    record.events.append(
        DiagnosticEvent(
            trace_id=record.trace_id,
            timestamp=datetime.now(UTC),
            stage=EventStage.RAG_SEARCH_COMPLETE,
            data={"dominio": "documentos_firmados", "hits": 2, "top_score": 0.2},
        )
    )
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.RAG_LOW_CONFIDENCE in types


def test_rag_low_confidence_not_flagged_above_threshold():
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("busca en los documentos algo sobre vacaciones")
    record.status = "completed"
    record.events.append(
        DiagnosticEvent(
            trace_id=record.trace_id,
            timestamp=datetime.now(UTC),
            stage=EventStage.RAG_SEARCH_COMPLETE,
            data={"dominio": "documentos_firmados", "hits": 2, "top_score": 0.9},
        )
    )
    analyze(record)
    types = [i.type for i in record.issues]
    assert DiagnosticIssueType.RAG_LOW_CONFIDENCE not in types


def test_rag_issues_not_duplicated_across_multiple_searches_in_same_trace():
    """Dos búsquedas RAG sin resultados en la misma traza deben producir un único issue RAG_NO_RESULTS."""
    from mia.diagnostics.analyzer import analyze
    from mia.diagnostics.models import DiagnosticIssueType, EventStage, DiagnosticEvent
    from datetime import UTC, datetime

    record = _make_trace("busca en nominas y documentos algo sobre dietas")
    record.status = "completed"
    for dominio in ("nominas", "documentos_firmados"):
        record.events.append(
            DiagnosticEvent(
                trace_id=record.trace_id,
                timestamp=datetime.now(UTC),
                stage=EventStage.RAG_SEARCH_COMPLETE,
                data={"dominio": dominio, "hits": 0, "top_score": None},
            )
        )
    analyze(record)
    types = [i.type for i in record.issues]
    assert types.count(DiagnosticIssueType.RAG_NO_RESULTS) == 1
