"""Almacén en memoria de trazas diagnósticas con retención configurable."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from mia.diagnostics.config import DiagnosticsSettings
from mia.diagnostics.models import TraceRecord


class DiagnosticsStore:
    """Almacén en memoria thread-safe (asyncio single-threaded) con límite y retención.

    Se inicializa una sola vez en ``create_app()``. El loop de limpieza corre como
    tarea de fondo y no bloquea el pipeline principal nunca.
    """

    def __init__(self, settings: DiagnosticsSettings) -> None:
        self._max = settings.max_traces
        self._retention = timedelta(hours=settings.retention_hours)
        self._traces: OrderedDict[str, TraceRecord] = OrderedDict()
        self._cleanup_task: asyncio.Task[None] | None = None

    # ── Escritura ─────────────────────────────────────────────────────────────

    def put(self, trace: TraceRecord) -> None:
        """Registra o actualiza una traza. Fire-and-forget: nunca lanza."""
        try:
            self._traces[trace.trace_id] = trace
            self._traces.move_to_end(trace.trace_id)
            if len(self._traces) > self._max:
                self._traces.popitem(last=False)  # descarta la más antigua
        except Exception:  # pragma: no cover — almacén nunca rompe el pipeline
            pass

    # ── Lectura ───────────────────────────────────────────────────────────────

    def get(self, trace_id: str) -> TraceRecord | None:
        return self._traces.get(trace_id)

    def list(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        domain: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[TraceRecord]:
        traces = list(reversed(self._traces.values()))
        if status:
            traces = [t for t in traces if t.status == status]
        if domain:
            traces = [t for t in traces if t.domain == domain]
        if user_id:
            traces = [t for t in traces if t.user_id == user_id]
        if session_id:
            traces = [t for t in traces if t.session_id == session_id]
        return traces[:limit]

    def running(self) -> list[TraceRecord]:
        return [t for t in self._traces.values() if t.status == "running"]

    def count(self) -> int:
        return len(self._traces)

    def metrics_window(self, *, minutes: int = 60) -> list[TraceRecord]:
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        return [t for t in self._traces.values() if t.started_at >= cutoff]

    # ── Limpieza ──────────────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        cutoff = datetime.now(UTC) - self._retention
        expired = [tid for tid, t in self._traces.items() if t.started_at < cutoff]
        for tid in expired:
            del self._traces[tid]

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(300)  # cada 5 minutos
            try:
                self._evict_expired()
            except Exception:  # pragma: no cover
                pass

    def start_cleanup(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def aclose(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

    # ── Etiquetado manual ─────────────────────────────────────────────────────

    def label(self, trace_id: str, label: str, notes: str | None = None) -> bool:
        trace = self._traces.get(trace_id)
        if not trace:
            return False
        trace.label = label
        if notes is not None:
            trace.developer_notes = notes
        return True

    # ── Estado global ─────────────────────────────────────────────────────────

    def to_status(self) -> dict[str, Any]:
        recent = self.metrics_window(minutes=60)
        completed = [t for t in recent if t.status == "completed"]
        errors = [t for t in recent if t.status == "error"]
        latencies = [t.elapsed_ms for t in completed if t.elapsed_ms is not None]
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else None
        avg = int(sum(latencies) / len(latencies)) if latencies else None
        return {
            "total_traces": self.count(),
            "running_traces": len(self.running()),
            "last_hour_requests": len(recent),
            "last_hour_errors": len(errors),
            "error_rate": round(len(errors) / len(recent), 3) if recent else 0.0,
            "avg_latency_ms": avg,
            "p95_latency_ms": p95,
        }
