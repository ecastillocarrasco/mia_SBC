"""Endpoints administrativos del sistema de diagnóstico.

Todos requieren ``Permission.ADMINISTRAR`` (rol ``mia.admin``).
Solo accesibles si ``settings.diagnostics.enabled = True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from mia.api.deps import ServicesDep, require
from mia.auth import Permission, UserContext
from mia.diagnostics import analyzer, is_enabled

router = APIRouter(prefix="/api/admin/diagnostics", tags=["diagnóstico"])

AdminDep = Annotated[UserContext, Depends(require(Permission.ADMINISTRAR))]

_PANEL_HTML = Path(__file__).parent / "panel.html"


def _require_enabled() -> None:
    if not is_enabled():
        raise HTTPException(status_code=404, detail="El módulo de diagnóstico no está habilitado (MIA_DIAGNOSTICS__ENABLED=false)")


# ── Panel HTML ────────────────────────────────────────────────────────────────

@router.get("/", include_in_schema=False)
async def panel(_: AdminDep) -> FileResponse:
    _require_enabled()
    return FileResponse(_PANEL_HTML, media_type="text/html")


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def status(services: ServicesDep, _: AdminDep) -> dict[str, Any]:
    _require_enabled()
    from mia.diagnostics import _store, _broadcaster  # type: ignore[attr-defined]

    store_status = _store.to_status() if _store else {}
    return {
        "diagnostics_enabled": True,
        "environment": services.settings.environment.value,
        "llm_provider": services.settings.llm.provider.value,
        "llm_model": services.settings.llm.model,
        "subscribers": _broadcaster.subscriber_count() if _broadcaster else 0,
        **store_status,
    }


# ── Listado de trazas ─────────────────────────────────────────────────────────

@router.get("/traces")
async def list_traces(
    _: AdminDep,
    limit: int = 50,
    status_filter: str | None = None,
    domain: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    _require_enabled()
    from mia.diagnostics import _store  # type: ignore[attr-defined]

    if _store is None:
        return []
    traces = _store.list(limit=limit, status=status_filter, domain=domain, user_id=user_id)
    return [t.to_summary() for t in traces]


# ── Detalle de una traza ──────────────────────────────────────────────────────

@router.get("/traces/{trace_id}")
async def get_trace(_: AdminDep, trace_id: str) -> dict[str, Any]:
    _require_enabled()
    from mia.diagnostics import _store  # type: ignore[attr-defined]

    trace = _store.get(trace_id) if _store else None
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Traza no encontrada: {trace_id}")
    assessment = analyzer.assess(trace)
    result = trace.to_dict()
    result["assessment"] = assessment
    return result


# ── Eventos de una traza ──────────────────────────────────────────────────────

@router.get("/traces/{trace_id}/events")
async def get_trace_events(_: AdminDep, trace_id: str) -> list[dict[str, Any]]:
    _require_enabled()
    from mia.diagnostics import _store  # type: ignore[attr-defined]

    trace = _store.get(trace_id) if _store else None
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Traza no encontrada: {trace_id}")
    return [e.to_dict() for e in trace.events]


# ── Métricas globales ─────────────────────────────────────────────────────────

@router.get("/metrics")
async def metrics(_: AdminDep, minutes: int = 60) -> dict[str, Any]:
    _require_enabled()
    from mia.diagnostics import _store  # type: ignore[attr-defined]
    from mia.diagnostics.metrics import compute_metrics

    if _store is None:
        return {}
    window = _store.metrics_window(minutes=minutes)
    return compute_metrics(window)


# ── Streaming en tiempo real (SSE) ────────────────────────────────────────────

@router.get("/live")
async def live_stream(_: AdminDep) -> StreamingResponse:
    _require_enabled()
    from mia.diagnostics import _broadcaster  # type: ignore[attr-defined]

    if _broadcaster is None:
        raise HTTPException(status_code=503, detail="Broadcaster no inicializado")

    q = _broadcaster.subscribe()
    return StreamingResponse(
        _broadcaster.stream(q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Etiquetado manual (Golden Dataset) ───────────────────────────────────────

class LabelRequest(BaseModel):
    label: str  # "correct" | "incorrect" | "needs_review" | "regression"
    notes: str | None = None


@router.put("/traces/{trace_id}/label")
async def label_trace(_: AdminDep, trace_id: str, body: LabelRequest) -> dict[str, Any]:
    _require_enabled()
    _VALID_LABELS = {"correct", "incorrect", "needs_review", "regression"}
    if body.label not in _VALID_LABELS:
        raise HTTPException(status_code=400, detail=f"Etiqueta no válida. Opciones: {_VALID_LABELS}")

    from mia.diagnostics import _store  # type: ignore[attr-defined]

    if _store is None or not _store.label(trace_id, body.label, body.notes):
        raise HTTPException(status_code=404, detail=f"Traza no encontrada: {trace_id}")
    return {"trace_id": trace_id, "label": body.label, "ok": True}
