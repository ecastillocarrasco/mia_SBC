"""Serialización de eventos a SSE (API nueva) y NDJSON (compatibilidad)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel


async def to_sse(events: AsyncIterator[BaseModel]) -> AsyncIterator[str]:
    async for event in events:
        kind = getattr(event, "type", "message")
        yield f"event: {kind}\ndata: {event.model_dump_json()}\n\n"


async def to_ndjson(
    events: AsyncIterator[BaseModel], transform: Callable[[BaseModel], dict[str, Any] | None]
) -> AsyncIterator[str]:
    async for event in events:
        payload = transform(event)
        if payload is not None:
            yield json.dumps(payload, ensure_ascii=False, default=str) + "\n"
