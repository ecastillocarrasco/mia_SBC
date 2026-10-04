"""Proveedor para la API Responses de OpenAI y de Azure OpenAI (``/openai/v1``).

Usa streaming SSE para empezar a hablar en cuanto el modelo produce la primera
frase, y salida estructurada para la respuesta final.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mia.llm.base import (
    LLMCompleted,
    LLMError,
    LLMEvent,
    LLMRequest,
    Message,
    TextDelta,
    ToolCall,
    ToolCallRequested,
)
from mia.observability import get_logger

log = get_logger(__name__)


def _input_items(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            items.append(
                {"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content}
            )
            continue
        if message.content:
            items.append({"role": message.role, "content": message.content})
        for call in message.tool_calls:
            items.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
            )
    return items


def build_payload(model: str, request: LLMRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "instructions": request.system,
        "input": _input_items(request.messages),
        "max_output_tokens": request.max_output_tokens,
        "stream": True,
        "store": False,
    }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "strict": False,
            }
            for tool in request.tools
        ]
    if request.response_schema is not None:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "respuesta_mia",
                "schema": request.response_schema,
                "strict": True,
            }
        }
    return payload


class OpenAIResponsesProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        azure: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"api-key": api_key} if azure else {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        payload = build_payload(self._model, request)
        try:
            async with self._client.stream("POST", "/responses", json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")[:500]
                    raise LLMError(f"HTTP {response.status_code}: {body}")
                async for event in self._parse_sse(response):
                    yield event
        except httpx.HTTPError as exc:
            raise LLMError(f"Error de red con el proveedor LLM: {exc}") from exc

    async def _parse_sse(self, response: httpx.Response) -> AsyncIterator[LLMEvent]:
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event: dict[str, Any] = json.loads(data)
            except json.JSONDecodeError:
                log.warning("llm.sse_invalid_line")
                continue
            kind = event.get("type")
            if kind == "response.output_text.delta":
                yield TextDelta(str(event.get("delta", "")))
            elif kind == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    yield ToolCallRequested(
                        ToolCall(
                            call_id=str(item.get("call_id")),
                            name=str(item.get("name")),
                            arguments=str(item.get("arguments") or "{}"),
                        )
                    )
            elif kind == "response.completed":
                usage = (event.get("response") or {}).get("usage") or {}
                details = usage.get("input_tokens_details") or {}
                yield LLMCompleted(
                    input_tokens=int(usage.get("input_tokens") or 0),
                    cached_tokens=int(details.get("cached_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                )
            elif kind in {"response.failed", "error"}:
                detail = event.get("error") or (event.get("response") or {}).get("error")
                raise LLMError(f"El proveedor LLM devolvió un error: {detail}")
