from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from mia.api.deps import ServicesDep, UserDep
from mia.api.schemas import ChatRequest
from mia.api.sse import to_sse
from mia.conversation import TurnResult

router = APIRouter(prefix="/api", tags=["conversación"])


async def prime[T](events: AsyncIterator[T]) -> AsyncIterator[T]:
    """Obtiene el primer evento antes de responder, para que los errores de
    sesión o permisos se devuelvan como error HTTP y no a mitad del stream."""
    first = await anext(events)

    async def chained() -> AsyncIterator[T]:
        yield first
        async for event in events:
            yield event

    return chained()


@router.post("/chat", response_model=TurnResult)
async def chat(body: ChatRequest, services: ServicesDep, user: UserDep) -> TurnResult:
    return await services.engine.complete(message=body.message, user=user, session_id=body.session_id)


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, services: ServicesDep, user: UserDep) -> StreamingResponse:
    """Eventos SSE: session, avatar, speech, progress, tool y result."""
    events = await prime(services.engine.run(message=body.message, user=user, session_id=body.session_id))
    return StreamingResponse(
        to_sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
