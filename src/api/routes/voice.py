from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from mia.api.deps import ServicesDep, UserDep
from mia.api.schemas import VoiceRequest
from mia.voice import CachedVoice, VoiceError

router = APIRouter(prefix="/api", tags=["voz"])


async def stream_speech(voice: CachedVoice, text: str) -> StreamingResponse:
    chunks = voice.stream(text)
    try:
        first = await anext(chunks)
    except StopAsyncIteration as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No hay texto que locutar") from exc
    except VoiceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La voz no está disponible") from exc

    async def body() -> AsyncIterator[bytes]:
        yield first
        try:
            async for chunk in chunks:
                yield chunk
        except VoiceError:
            return

    return StreamingResponse(body(), media_type=voice.media_type, headers={"Cache-Control": "no-store"})


@router.post("/voice/stream")
async def voice_stream(body: VoiceRequest, services: ServicesDep, _: UserDep) -> StreamingResponse:
    """Audio en streaming: empieza a sonar con el primer bloque."""
    return await stream_speech(services.voice, body.text)
