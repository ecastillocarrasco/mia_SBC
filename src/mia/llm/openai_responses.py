"""Proveedor para la API Responses de OpenAI y de Azure OpenAI (``/openai/v1``).

Usa streaming SSE para empezar a hablar en cuanto el modelo produce la primera
frase, y salida estructurada para la respuesta final.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    WebSources,
)
from mia.observability import get_logger

log = get_logger(__name__)


def _input_items(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            items.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content})
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


def _clean_url(url: str) -> str | None:
    """Solo enlaces http(s); se quita el rastreo que añade el proveedor (utm_source=openai)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not (k == "utm_source" and v == "openai")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def extract_web_sources(output_items: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    """Fuentes web de la salida del proveedor: las CITADAS en el texto (url_citation) y, si no hay ninguna,
    las que consultó la búsqueda. Devuelve enlaces únicos y seguros, con su título."""
    cited: dict[str, str] = {}
    consulted: dict[str, str] = {}
    for item in output_items:
        for part in item.get("content") or []:
            for note in part.get("annotations") or []:
                if note.get("type") == "url_citation" and (url := _clean_url(str(note.get("url") or ""))):
                    cited.setdefault(url, str(note.get("title") or "").strip())
        for source in (item.get("action") or {}).get("sources") or []:
            if url := _clean_url(str(source.get("url") or "")):
                consulted.setdefault(url, str(source.get("title") or "").strip())
    chosen = cited or consulted
    return tuple({"url": url, "title": title} for url, title in chosen.items())


def build_payload(model: str, request: LLMRequest, *, web_search: bool | str = False) -> dict[str, Any]:
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
    if web_search:
        payload.setdefault("tools", []).append({"type": web_search if isinstance(web_search, str) else "web_search"})
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


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    try:
        return min(float(retry_after), 10.0) if retry_after else min(0.8 * float(2**attempt), 6.0)
    except ValueError:
        return min(0.8 * float(2**attempt), 6.0)


class OpenAIResponsesProvider:
    MAX_RETRIES = 3
    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        azure: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        web_search: bool = False,
    ) -> None:
        # Nombre de la herramienta de búsqueda que se prueba; si el proveedor la rechaza se prueba la
        # siguiente («web_search_preview» en modelos/despliegues más antiguos) y, si ninguna, se desactiva.
        self._web_search_options = ["web_search", "web_search_preview"] if web_search else []
        self._web_search: str | bool = self._web_search_options[0] if web_search else False
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

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Embeddings para la búsqueda semántica (en Azure, «model» es el nombre del despliegue)."""
        try:
            response = await self._client.post("/embeddings", json={"model": model, "input": texts})
        except httpx.HTTPError as exc:
            raise LLMError(f"Error de red al calcular embeddings: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"Embeddings HTTP {response.status_code}: {response.text[:300]}")
        data = sorted(response.json().get("data", []), key=lambda d: d.get("index", 0))
        return [list(map(float, d["embedding"])) for d in data]

    async def read_image(self, content: bytes, media_type: str, instruction: str) -> str:
        """Transcripción de una imagen (CVs escaneados o fotografiados) con el modelo multimodal."""
        image = f"data:{media_type};base64,{base64.b64encode(content).decode()}"
        payload = {
            "model": self._model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instruction},
                        {"type": "input_image", "image_url": image},
                    ],
                }
            ],
        }
        try:
            response = await self._client.post("/responses", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Error de red al leer la imagen: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"Lectura de imagen HTTP {response.status_code}: {response.text[:300]}")
        parts = [
            c.get("text", "")
            for item in response.json().get("output", [])
            for c in item.get("content", []) or []
            if c.get("type") == "output_text"
        ]
        return "\n".join(parts)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        payload = build_payload(self._model, request, web_search=self._web_search)
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                async with self._client.stream("POST", "/responses", json=payload) as response:
                    if response.status_code in self.RETRY_STATUS and attempt < self.MAX_RETRIES:
                        await response.aread()
                        delay = _retry_delay(response.headers.get("retry-after"), attempt)
                        log.warning("llm.retry", status=response.status_code, attempt=attempt + 1, delay=delay)
                        await asyncio.sleep(delay)
                        continue
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")[:500]
                        if response.status_code == 400 and self._web_search and "web_search" in body:
                            self._web_search_options = self._web_search_options[1:]
                            self._web_search = self._web_search_options[0] if self._web_search_options else False
                            log.warning(
                                "llm.web_search_changed", now=self._web_search or "desactivada", reason=body[:200]
                            )
                            payload = build_payload(self._model, request, web_search=self._web_search)
                            continue
                        raise LLMError(f"HTTP {response.status_code}: {body}")
                    async for event in self._parse_sse(response):
                        yield event
                    return
            except httpx.TimeoutException as exc:
                if attempt < self.MAX_RETRIES:
                    log.warning("llm.retry", reason="timeout", attempt=attempt + 1)
                    continue
                raise LLMError(f"El proveedor LLM no respondió a tiempo: {exc}") from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"Error de red con el proveedor LLM: {exc}") from exc

    async def _parse_sse(self, response: httpx.Response) -> AsyncIterator[LLMEvent]:  # noqa: PLR0912
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
            elif kind == "response.output_text.annotation.added":
                if found := extract_web_sources([{"content": [{"annotations": [event.get("annotation") or {}]}]}]):
                    yield WebSources(found)
            elif kind == "response.output_item.done":
                item = event.get("item") or {}
                if found := extract_web_sources([item]):
                    yield WebSources(found)
                if item.get("type") == "function_call":
                    yield ToolCallRequested(
                        ToolCall(
                            call_id=str(item.get("call_id")),
                            name=str(item.get("name")),
                            arguments=str(item.get("arguments") or "{}"),
                        )
                    )
            elif kind == "response.completed":
                if found := extract_web_sources((event.get("response") or {}).get("output") or []):
                    yield WebSources(found)
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
