"""Endpoints administrativos del sistema de diagnóstico.

Acceso deliberadamente aparte del resto de la app: no usa ``Permission``/Entra ID como las rutas
de negocio (``Authorization: Bearer``), porque esa cabecera nunca puede llegar en una navegación
directa de página -- no hay JS corriendo todavía para adjuntarla, así que cualquier ruta gateada
así es inalcanzable desde un navegador normal (escribir la URL, un marcador). En su lugar, HTTP
Basic Auth: el navegador lo negocia solo con un diálogo nativo en la primera petición a este
origen/realm, y cachea las credenciales para toda petición posterior al mismo origen -- incluidos
los ``fetch()`` propios del panel y el ``EventSource`` de ``/live`` (que no puede llevar cabeceras
personalizadas), sin ninguna lógica adicional en el HTML.

Autorizados: los emails exactos de ``settings.diagnostics.admin_users`` con la contraseña
compartida ``admin_password`` -- una lista cerrada de personas (3 a día de hoy), no un rol de la
app ni nada ligado a Entra ID. Solo accesible si ``settings.diagnostics.enabled = True``.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from mia.api.deps import ServicesDep
from mia.diagnostics import analyzer, is_enabled

router = APIRouter(prefix="/api/admin/diagnostics", tags=["diagnóstico"])

_PANEL_HTML = Path(__file__).parent / "panel.html"

_WWW_AUTHENTICATE = {"WWW-Authenticate": 'Basic realm="mIA Diagnostics"'}


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Acceso restringido", headers=_WWW_AUTHENTICATE)


async def _require_diagnostics_admin(request: Request, services: ServicesDep) -> str:
    """Basic Auth parseado a mano en vez de ``fastapi.security.HTTPBasic``: esa clase decodifica
    las credenciales como ASCII puro (``b64decode(param).decode("ascii")``) y lanza 401 siempre
    que falle -- incluso con ``auto_error=False`` -- así que una contraseña con tilde o «ñ» (nada
    raro para un admin de aquí) rompería el login de forma no obvia. Aquí se decodifica en UTF-8."""
    diag = services.settings.diagnostics
    expected_password = diag.admin_password.get_secret_value()
    allowed_emails = {email.strip().lower() for email in diag.admin_users if email.strip()}

    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise _unauthorized()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise _unauthorized() from exc
    username, separator, password = decoded.partition(":")
    if not separator:
        raise _unauthorized()
    username = username.strip().lower()

    user_ok = username in allowed_emails
    password_ok = bool(expected_password) and secrets.compare_digest(
        password.encode("utf-8"), expected_password.encode("utf-8")
    )
    if not user_ok or not password_ok:
        raise _unauthorized()
    return username


DiagAdminDep = Annotated[str, Depends(_require_diagnostics_admin)]


def _require_enabled() -> None:
    if not is_enabled():
        raise HTTPException(
            status_code=404, detail="El módulo de diagnóstico no está habilitado (MIA_DIAGNOSTICS__ENABLED=false)"
        )


# ── Panel HTML ────────────────────────────────────────────────────────────────


@router.get("/", include_in_schema=False)
async def panel(_: DiagAdminDep) -> FileResponse:
    _require_enabled()
    return FileResponse(_PANEL_HTML, media_type="text/html")


# ── Status ────────────────────────────────────────────────────────────────────


@router.get("/status")
async def status(services: ServicesDep, _: DiagAdminDep) -> dict[str, Any]:
    _require_enabled()
    from mia.diagnostics import _broadcaster, _store  # type: ignore[attr-defined]

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
    _: DiagAdminDep,
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
async def get_trace(_: DiagAdminDep, trace_id: str) -> dict[str, Any]:
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
async def get_trace_events(_: DiagAdminDep, trace_id: str) -> list[dict[str, Any]]:
    _require_enabled()
    from mia.diagnostics import _store  # type: ignore[attr-defined]

    trace = _store.get(trace_id) if _store else None
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Traza no encontrada: {trace_id}")
    return [e.to_dict() for e in trace.events]


# ── Métricas globales ─────────────────────────────────────────────────────────


@router.get("/metrics")
async def metrics(_: DiagAdminDep, minutes: int = 60) -> dict[str, Any]:
    _require_enabled()
    from mia.diagnostics import _store  # type: ignore[attr-defined]
    from mia.diagnostics.metrics import compute_metrics

    if _store is None:
        return {}
    window = _store.metrics_window(minutes=minutes)
    return compute_metrics(window)


# ── Streaming en tiempo real (SSE) ────────────────────────────────────────────


@router.get("/live")
async def live_stream(_: DiagAdminDep) -> StreamingResponse:
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
async def label_trace(_: DiagAdminDep, trace_id: str, body: LabelRequest) -> dict[str, Any]:
    _require_enabled()
    _VALID_LABELS = {"correct", "incorrect", "needs_review", "regression"}
    if body.label not in _VALID_LABELS:
        raise HTTPException(status_code=400, detail=f"Etiqueta no válida. Opciones: {_VALID_LABELS}")

    from mia.diagnostics import _store  # type: ignore[attr-defined]

    if _store is None or not _store.label(trace_id, body.label, body.notes):
        raise HTTPException(status_code=404, detail=f"Traza no encontrada: {trace_id}")
    return {"trace_id": trace_id, "label": body.label, "ok": True}
