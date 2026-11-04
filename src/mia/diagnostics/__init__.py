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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mia.diagnostics.alerting import notify_on_error
from mia.diagnostics.models import EventStage, EventStatus, TraceStatus
from mia.diagnostics.trace import TraceContext, current_call_id, current_trace, noop_trace  # noqa: F401
from mia.diagnostics.trace import begin_trace as _begin_trace

if TYPE_CHECKING:
    from mia.diagnostics.store import DiagnosticsStore
    from mia.diagnostics.streaming import LiveBroadcaster
    from mia.settings import SmtpSettings


@dataclass
class _DiagnosticsState:
    store: DiagnosticsStore | None = None
    broadcaster: LiveBroadcaster | None = None
    mask_pii: bool = False
    alert_email: str = ""
    smtp: SmtpSettings | None = None
    alert_cooldown_seconds: int = 60
    pending_alerts: set[asyncio.Task[None]] = field(default_factory=set)
    """Mantiene viva la referencia a cada aviso fire-and-forget hasta que termina (asyncio solo
    retiene una referencia débil a una tarea sin dueño: sin esto, el recolector de basura podría
    cancelarla a mitad de camino)."""


_state = _DiagnosticsState()


def is_enabled() -> bool:
    return _state.store is not None


def setup(
    store: DiagnosticsStore,
    broadcaster: LiveBroadcaster,
    *,
    mask_pii: bool = False,
    alert_email: str = "",
    smtp: SmtpSettings | None = None,
    alert_cooldown_seconds: int = 60,
) -> None:
    """Inicializa el módulo de diagnóstico. Llamado desde create_app() si enabled=True."""
    _state.store = store
    _state.broadcaster = broadcaster
    _state.mask_pii = mask_pii
    _state.alert_email = alert_email
    _state.smtp = smtp
    _state.alert_cooldown_seconds = alert_cooldown_seconds


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
        try:
            yield ctx
        finally:
            # Al salir de este bloque, ctx.record.status ya es definitivo (lo fija engine.py o,
            # en un fallo inesperado, el propio _begin_trace). Se agenda sin esperar: no debe
            # retrasar ni poner en riesgo la respuesta ya calculada para el usuario.
            if _state.alert_email and _state.smtp is not None:
                # Fire-and-forget: nadie espera ni cancela este aviso, pero se guarda la
                # referencia en pending_alerts (ver _DiagnosticsState) hasta que termina.
                _alert_task = asyncio.create_task(
                    notify_on_error(
                        ctx.record,
                        recipient=_state.alert_email,
                        smtp=_state.smtp,
                        cooldown_seconds=_state.alert_cooldown_seconds,
                    )
                )
                _state.pending_alerts.add(_alert_task)
                _alert_task.add_done_callback(_state.pending_alerts.discard)


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
