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
from typing import TYPE_CHECKING, Any

from mia.diagnostics.models import EventStage, EventStatus, TraceStatus  # noqa: F401
from mia.diagnostics.trace import TraceContext, current_call_id, current_trace, noop_trace  # noqa: F401

if TYPE_CHECKING:
    from mia.diagnostics.store import DiagnosticsStore
    from mia.diagnostics.streaming import LiveBroadcaster

# Singletons — inicializados en create_app() si enabled=True
_store: DiagnosticsStore | None = None
_broadcaster: LiveBroadcaster | None = None
_mask_pii: bool = False


def is_enabled() -> bool:
    return _store is not None


def setup(store: DiagnosticsStore, broadcaster: LiveBroadcaster, *, mask_pii: bool = False) -> None:
    """Inicializa el módulo de diagnóstico. Llamado desde create_app() si enabled=True."""
    global _store, _broadcaster, _mask_pii
    _store = store
    _broadcaster = broadcaster
    _mask_pii = mask_pii


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
    if _store is None or _broadcaster is None:
        yield None
        return

    from mia.diagnostics.trace import begin_trace as _begin_trace

    async with _begin_trace(
        query=query,
        user_id=user_id,
        user_name=user_name,
        session_id=session_id,
        request_id=request_id,
        store=_store,
        broadcaster=_broadcaster,
        mask_pii=_mask_pii,
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
    "is_enabled",
    "setup",
    "begin_trace",
    "emit",
    "current_trace",
    "current_call_id",
    "EventStage",
    "EventStatus",
    "TraceStatus",
    "TraceContext",
]
