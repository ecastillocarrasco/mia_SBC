"""Alias de compatibilidad con el frontend actual.

El frontend existente llama a estas rutas y espera su formato de respuesta.
Se mantienen hasta rehacer el frontend; después se eliminan en bloque.
El contexto que envía el cliente se ignora salvo ``session_id``: el estado
de la conversación vive en el servidor.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mia import __version__
from mia.api.deps import ServicesDep, UserDep
from mia.api.routes.chat import prime
from mia.api.routes.voice import stream_speech
from mia.api.sse import to_ndjson
from mia.conversation import TurnResult
from mia.conversation.events import ProgressEvent, ResultEvent, ToolEvent

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
    primary = result.presentations[0] if result.presentations else {}
    return {
        "status": "ok" if result.status == "ok" else "error",
        "answer": result.answer,
        "speech": result.speech,
        "avatar_state": result.avatar_state,
        "avatar": {"state": result.avatar_state},
        "data": dict(primary),
        "visualizations": result.presentations,
        "actions": [],
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
async def legacy_chat_stream(
    body: LegacyChatRequest, services: ServicesDep, user: UserDep
) -> StreamingResponse:
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
