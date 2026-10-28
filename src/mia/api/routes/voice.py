from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from mia.api.deps import ServicesDep, UserDep
from mia.api.schemas import VoiceRequest, WelcomeResponse
from mia.voice import CachedVoice, VoiceError
from mia.voice.greeting import first_name_from_display_name, welcome_text

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


@router.get("/voice/welcome")
async def voice_welcome(
    user: UserDep, name: str | None = Query(default=None, max_length=40)
) -> WelcomeResponse:
    """Saludo inicial hablado, con el nombre del usuario autenticado.

    Única fuente del texto de bienvenida: 2D, 3D, holograma y mIA Desktop lo piden
    aquí en vez de llevar cada uno su propia copia de las frases (ver mia.voice.greeting).
    ``name`` es un override explícito y opcional (mIA Desktop permite escribir un
    nombre propio en Ajustes); sin él, se usa el nombre del usuario autenticado.
    """
    first_name = first_name_from_display_name(name) or first_name_from_display_name(user.display_name)
    return WelcomeResponse(text=welcome_text(first_name))
