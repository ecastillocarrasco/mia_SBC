"""Sistema de diagnóstico interno de mIA.

API pública:

    from mia.diagnostics import is_enabled, begin_trace, current_trace

Uso en engine.py (ejemplo simplificado):

    from mia import diagnostics

    async with diagnostics.begin_trace(query=message, ...) as trace:
        trace.emit(EventStage.REQUEST_RECEIVED)
        ...

Cuando ``MIA_DIAGNOSTICS__ENABLED=false`` (por defecto):
- ``is_enabled()`` → False
- ``begin_trace(...)`` devuelve el contexto noop (yield None)
- ``current_trace()`` → None
- ``emit(...)`` hace nada
- Overhead ≈ 0

"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mia.diagnostics.models import EventStage, EventStatus, TraceStatus
from mia.diagnostics.trace import TraceContext, current_call_id, current_trace, noop_trace  # noqa: F401
from mia.diagnostics.trace import begin_trace as _begin_trace

if TYPE_CHECKING:
    from mia.diagnostics.store import DiagnosticsStore
    from mia.diagnostics.streaming import LiveBroadcaster


@dataclass
class _DiagnosticsState:
    store: DiagnosticsStore | None = None
    broadcaster: LiveBroadcaster | None = None
    mask_pii: bool = False


_state = _DiagnosticsState()


def is_enabled() -> bool:
    return _state.store is not None


def setup(store: DiagnosticsStore, broadcaster: LiveBroadcaster, *, mask_pii: bool = False) -> None:
    """Inicializa el módulo de diagnóstico. Llamado desde create_app() si enabled=True."""
    _state.store = store
    _state.broadcaster = broadcaster
    _state.mask_pii = mask_pii


@asynccontextmanager
async def begin_trace(
    *,
    query: str,
    user_id: str | None = None,
    user_name: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
) -> AsyncIterator[TraceContext | None]:
    """Crea una traza para el turno actual.

    - Si diagnósticos desactivados: yield None (sin overhead).
    - Si activados: crea TraceContext, lo fija en el ContextVar y lo cierra al salir.
    """
    if _state.store is None or _state.broadcaster is None:
        yield None
        return

    async with _begin_trace(
        query=query,
        user_id=user_id,
        user_name=user_name,
        session_id=session_id,
        request_id=request_id,
        store=_state.store,
        broadcaster=_state.broadcaster,
        mask_pii=_state.mask_pii,
    ) as ctx:
        yield ctx


def emit(
    stage: str | EventStage,
    *,
    status: str = EventStatus.INFO,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
    **metadata: Any,
) -> None:
    """Emite un evento en la traza activa del contexto actual. No-op si no hay traza."""
    trace = current_trace()
    if trace is None:
        return
    trace.emit(stage, status=status, duration_ms=duration_ms, data=data, **metadata)


__all__ = [
    "EventStage",
    "EventStatus",
    "TraceContext",
    "TraceStatus",
    "begin_trace",
    "current_call_id",
    "current_trace",
    "emit",
    "is_enabled",
    "setup",
]
