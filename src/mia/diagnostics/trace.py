"""TraceContext: ciclo de vida de una traza diagnóstica, propagado via ContextVar."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from mia.diagnostics.models import DiagnosticEvent, DiagnosticIssue, EventStage, EventStatus, TraceStatus, TraceRecord
from mia.diagnostics.sanitizer import redact

_current_trace: ContextVar[TraceContext | None] = ContextVar("_mia_trace", default=None)
_current_call_id: ContextVar[str | None] = ContextVar("_mia_call_id", default=None)


def current_trace() -> TraceContext | None:
    """Devuelve la traza activa en el contexto actual (None si diagnósticos desactivados)."""
    return _current_trace.get()


def current_call_id() -> str | None:
    """Devuelve el call_id de la herramienta en ejecución (para vincular nodos SQL a su herramienta padre)."""
    return _current_call_id.get()


def new_trace_id() -> str:
    now = datetime.now(UTC)
    suffix = uuid.uuid4().hex[:8]
    return f"mia-{now.strftime('%Y%m%d-%H%M%S')}-{suffix}"


class TraceContext:
    """Contexto mutable de una traza para un único turno conversacional.

    Diseñado para usarse desde ``engine.run()``:
    - Se crea una instancia por turno.
    - Se registra en el ContextVar para que las herramientas puedan emitir eventos sin recibir
      el contexto como parámetro explícito.
    - Los eventos se almacenan en la TraceRecord y se retransmiten al panel vía LiveBroadcaster.
    - Si el store o el broadcaster fallan, el error se suprime: el pipeline nunca falla por diagnósticos.
    """

    def __init__(
        self,
        record: TraceRecord,
        store: Any,  # DiagnosticsStore (any para evitar import circular)
        broadcaster: Any,  # LiveBroadcaster
        mask_pii: bool = False,
    ) -> None:
        self._record = record
        self._store = store
        self._broadcaster = broadcaster
        self._mask_pii = mask_pii

    @property
    def trace_id(self) -> str:
        return self._record.trace_id

    @property
    def record(self) -> TraceRecord:
        return self._record

    def emit(
        self,
        stage: str | EventStage,
        *,
        status: str = EventStatus.INFO,
        duration_ms: int | None = None,
        data: dict[str, Any] | None = None,
        **metadata: Any,
    ) -> None:
        """Registra un evento en la traza. Nunca lanza excepciones."""
        try:
            safe_data = redact(data or {}, mask_pii=self._mask_pii)
            event = DiagnosticEvent(
                trace_id=self._record.trace_id,
                timestamp=datetime.now(UTC),
                stage=str(stage),
                status=str(status),
                duration_ms=duration_ms,
                data=safe_data,
                metadata=metadata,
            )
            self._record.events.append(event)

            # Actualiza campos de resumen según la fase
            self._update_summary(stage, data or {})

            # Actualiza la traza en el store
            self._store.put(self._record)

            # Retransmite al panel en tiempo real
            self._broadcaster.publish(
                {"type": "event", "trace_id": self._record.trace_id, **event.to_dict()}
            )
        except Exception:  # pragma: no cover — diagnósticos nunca rompen el pipeline
            pass

    def _update_summary(self, stage: str | EventStage, data: dict[str, Any]) -> None:
        """Actualiza los campos de resumen de la TraceRecord basándose en el stage."""
        s = str(stage)
        if s == EventStage.DOMAIN_DETECTION:
            self._record.modules = data.get("modules", [])
            if data.get("modules"):
                self._record.domain = ", ".join(data["modules"])
        elif s == EventStage.TOOL_CALL_START:
            tool_name = data.get("tool", "")
            if tool_name and tool_name not in self._record.tools_called:
                self._record.tools_called.append(tool_name)
        elif s == EventStage.TOOL_CALL_ERROR:
            self._record.tool_errors += 1
            self._record.error_count += 1
        elif s == EventStage.LLM_REQUEST:
            self._record.llm_rounds += 1
        elif s == EventStage.LLM_RESPONSE:
            self._record.tokens_input += data.get("input_tokens", 0)
            self._record.tokens_output += data.get("output_tokens", 0)
            self._record.tokens_cached += data.get("cached_tokens", 0)
        elif s == EventStage.ERROR or s == EventStage.EXCEPTION:
            self._record.error_count += 1
        elif s == EventStage.WARNING:
            self._record.warning_count += 1
        elif s == EventStage.PRESENTATION_SELECTED:
            p_type = data.get("type", "")
            if p_type:
                self._record.presentations.append(p_type)

    def add_issue(self, issue_type: str, message: str, **details: Any) -> None:
        self._record.issues.append(DiagnosticIssue(type=issue_type, message=message, details=details))

    def add_call_graph_node(self, node: dict[str, Any]) -> None:
        """Añade un nodo al grafo de ejecución de la traza. Nunca lanza excepciones."""
        try:
            self._record.call_graph.append(node)
        except Exception:  # pragma: no cover
            pass

    def finish(
        self,
        *,
        answer: str | None = None,
        status: str = TraceStatus.COMPLETED,
        llm_model: str | None = None,
    ) -> None:
        """Cierra la traza con estado final."""
        try:
            now = datetime.now(UTC)
            self._record.completed_at = now
            self._record.elapsed_ms = int((now - self._record.started_at).total_seconds() * 1000)
            self._record.status = str(status)
            if answer is not None:
                self._record.final_answer = answer[:1000]  # nunca datos muy largos
            if llm_model:
                self._record.llm_model = llm_model
            self.emit(EventStage.TRACE_COMPLETE, status=EventStatus.SUCCESS, data={"elapsed_ms": self._record.elapsed_ms})
            self._store.put(self._record)
            self._broadcaster.publish(
                {"type": "trace_complete", "trace_id": self._record.trace_id, **self._record.to_summary()}
            )
        except Exception:  # pragma: no cover
            pass


@asynccontextmanager
async def begin_trace(
    *,
    query: str,
    user_id: str | None = None,
    user_name: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    store: Any,
    broadcaster: Any,
    mask_pii: bool = False,
) -> AsyncIterator[TraceContext]:
    """Context manager asíncrono: crea la traza, la fija en el ContextVar y la cierra al salir."""
    trace_id = new_trace_id()
    record = TraceRecord(
        trace_id=trace_id,
        started_at=datetime.now(UTC),
        query=query,
        request_id=request_id,
        session_id=session_id,
        user_id=user_id,
        user_name=user_name,
    )
    ctx = TraceContext(record, store, broadcaster, mask_pii=mask_pii)
    token = _current_trace.set(ctx)
    store.put(record)
    broadcaster.publish({"type": "trace_start", "trace_id": trace_id, **record.to_summary()})
    try:
        yield ctx
    except Exception as exc:
        ctx.emit(
            EventStage.EXCEPTION,
            status=EventStatus.ERROR,
            data={"error": str(exc)},
        )
        ctx.finish(status=TraceStatus.ERROR)
        raise
    finally:
        try:
            _current_trace.reset(token)
        except ValueError:
            # El generador fue cerrado desde un contexto asyncio diferente al que lo creó
            # (SSE stream cerrado por el cliente). El reset falla pero es seguro ignorarlo.
            pass
        # Si finish() no fue llamado explícitamente (error inesperado), cierro aquí
        if record.status == TraceStatus.RUNNING:
            ctx.finish(status=TraceStatus.ERROR)


# ── Noop context manager para cuando diagnostics está desactivado ─────────────

@asynccontextmanager
async def noop_trace() -> AsyncIterator[None]:
    yield None
