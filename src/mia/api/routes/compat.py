"""Alias de compatibilidad con el frontend actual.

El frontend existente llama a estas rutas y espera su formato de respuesta.
Se mantienen hasta rehacer el frontend; después se eliminan en bloque.
El contexto que envía el cliente se ignora salvo ``session_id``: el estado
de la conversación vive en el servidor.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from mia import __version__
from mia.api.deps import ServicesDep, UserDep
from mia.api.legacy_view import legacy_view
from mia.api.routes.chat import prime
from mia.api.routes.reports import MEDIA
from mia.api.routes.voice import stream_speech
from mia.api.sse import to_ndjson
from mia.conversation import TurnResult
from mia.conversation.events import ProgressEvent, ResultEvent, ToolEvent
from mia.conversation.tools import ToolContext, ToolStatus
from mia.domains.informes.document import to_document
from mia.domains.informes.render import RENDERERS
from mia.llm import ToolCall
from mia.observability import current_request_id
from mia.text import normalize_key

router = APIRouter(tags=["compatibilidad"], include_in_schema=False)


class LegacyChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)

    @property
    def session_id(self) -> str | None:
        value = self.context.get("session_id")
        return str(value)[:32] if isinstance(value, str) and value else None


class LegacyVoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    locale: str | None = None


def legacy_payload(result: TurnResult) -> dict[str, Any]:
    data, actions = legacy_view(result.presentations, result.summaries)
    return {
        "status": "ok" if result.status == "ok" else "error",
        "answer": result.answer,
        "speech": result.speech,
        "avatar_state": result.avatar_state,
        "avatar": {"state": result.avatar_state},
        "data": data,
        "actions": actions,
        "presentations": result.presentations,
        "context": {"session_id": result.session_id},
        "meta": {"elapsed_ms": result.elapsed_ms, "engine": "mia", "version": __version__},
    }


def _legacy_stream_event(event: BaseModel) -> dict[str, Any] | None:
    if isinstance(event, ResultEvent):
        return {"type": "result", "payload": legacy_payload(event.result)}
    if isinstance(event, ProgressEvent):
        return {"type": "progress", "stage": event.stage, "message": event.message}
    if isinstance(event, ToolEvent):
        return {"type": "progress", "stage": event.name, "message": f"{event.name}: {event.status}"}
    return None


@router.post("/api/mia/chat")
@router.post("/api/mia/v4/chat")
async def legacy_chat(body: LegacyChatRequest, services: ServicesDep, user: UserDep) -> dict[str, Any]:
    result = await services.engine.complete(message=body.message, user=user, session_id=body.session_id)
    return legacy_payload(result)


@router.post("/api/mia/chat/stream")
async def legacy_chat_stream(body: LegacyChatRequest, services: ServicesDep, user: UserDep) -> StreamingResponse:
    events = await prime(services.engine.run(message=body.message, user=user, session_id=body.session_id))
    return StreamingResponse(to_ndjson(events, _legacy_stream_event), media_type="application/x-ndjson")


@router.post("/api/mia/voice")
async def legacy_voice(body: LegacyVoiceRequest, services: ServicesDep, _: UserDep) -> StreamingResponse:
    return await stream_speech(services.voice, body.text)


@router.get("/api/version")
async def legacy_version() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "runtime": "mia"}


@router.get("/api/mia/v4/health")
async def legacy_llm_health(services: ServicesDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "model": services.settings.llm.model,
        "provider": services.settings.llm.provider.value,
        "assistant_identity": "mIA",
    }


# ------------------------------------------------------------------ informes (botones del frontend actual)
LEGACY_MODULES: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "ficha360": ("ficha_empleado", lambda body: {"nombre": body.get("nombre")}),
    "dashboard_rrhh": ("panel_rrhh", lambda body: {}),
    "dashboard": ("panel_rrhh", lambda body: {}),
    "rrhh": ("panel_rrhh", lambda body: {}),
    "departamentos": ("estructura_departamentos", lambda body: {}),
    "empleados": ("plantilla", lambda body: {}),
    "empleados_calidad": ("calidad_datos", lambda body: {}),
    "vacaciones_pendientes": ("vacaciones", lambda body: {"estado": "pendientes"}),
    "vacaciones_analitica": ("analitica_vacaciones", lambda body: {"anio": body.get("anio")}),
    "saldo_vacaciones": ("saldo_vacaciones", lambda body: {}),
    "curriculums": ("candidaturas", lambda body: {}),
    "nominas": ("nominas_persona", lambda body: {"nombre": body.get("nombre"), "anio": body.get("anio")}),
}


@router.post("/api/mia/informes/generar")
async def legacy_report(body: dict[str, Any], services: ServicesDep, user: UserDep) -> Response:
    """Botones «Informe PDF / Exportar Excel» del frontend actual: genera el fichero y lo devuelve."""
    module = normalize_key(str(body.get("modulo") or "")).replace(" ", "_")
    fmt = {"excel": "xlsx", "xls": "xlsx"}.get(
        str(body.get("formato") or "pdf").lower(), str(body.get("formato") or "pdf").lower()
    )
    if module not in LEGACY_MODULES or fmt not in RENDERERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Módulo o formato de informe no soportado")
    tool, args = LEGACY_MODULES[module]
    params = {k: v for k, v in args(body).items() if v not in (None, "")}
    ctx = ToolContext(
        user=user, request_id=current_request_id(), now=datetime.now(ZoneInfo(services.settings.timezone))
    )
    execution = await services.engine.tools.execute(ToolCall("informe", tool, json.dumps(params)), ctx)
    if execution.result.status is not ToolStatus.OK or not execution.result.presentation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay datos para ese informe")
    document = to_document(execution.result.presentation)
    logo = services.settings.reports.logo_path
    content = await asyncio.to_thread(RENDERERS[fmt], document, ctx.now, logo if logo and logo.is_file() else None)
    name = re.sub(r"[^\w\- ]+", "", document.title).strip()[:60] or "informe"
    return Response(
        content,
        media_type=MEDIA.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'},
    )
