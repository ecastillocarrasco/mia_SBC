from __future__ import annotations

import json

import httpx
import pytest

from mia.llm import (
    LLMCompleted,
    LLMError,
    LLMRequest,
    Message,
    TextDelta,
    ToolCall,
    ToolCallRequested,
    ToolSchema,
)
from mia.llm.openai_responses import OpenAIResponsesProvider, build_payload


def _sse(*events: dict[str, object]) -> bytes:
    return "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _provider(handler: httpx.MockTransport, azure: bool = False) -> OpenAIResponsesProvider:
    return OpenAIResponsesProvider(
        api_key="k",
        model="m",
        base_url="https://llm.test/v1",
        timeout_seconds=5,
        azure=azure,
        transport=handler,
    )


def test_payload_includes_tools_history_and_schema() -> None:
    request = LLMRequest(
        system="sys",
        messages=[
            Message("user", "hola"),
            Message("assistant", "", tool_calls=(ToolCall("c1", "t", "{}"),)),
            Message("tool", '{"ok":1}', tool_call_id="c1"),
        ],
        tools=[ToolSchema("t", "desc", {"type": "object", "properties": {}})],
        response_schema={"type": "object"},
    )
    payload = build_payload("gpt", request)
    assert payload["instructions"] == "sys"
    assert payload["input"] == [
        {"role": "user", "content": "hola"},
        {"type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": '{"ok":1}'},
    ]
    assert payload["tools"][0]["name"] == "t"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["store"] is False


async def test_stream_parses_text_tools_and_usage() -> None:
    seen: dict[str, httpx.Request] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["req"] = request
        body = _sse(
            {"type": "response.output_text.delta", "delta": "Hol"},
            {"type": "response.output_text.delta", "delta": "a"},
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "call_id": "c9", "name": "capacidades", "arguments": "{}"},
            },
            {
                "type": "response.completed",
                "response": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "input_tokens_details": {"cached_tokens": 8},
                    }
                },
            },
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = _provider(httpx.MockTransport(handle), azure=True)
    events = [e async for e in provider.stream(LLMRequest(system="s", messages=[Message("user", "x")]))]
    await provider.aclose()

    assert seen["req"].headers["api-key"] == "k"
    assert seen["req"].url.path == "/v1/responses"
    assert events == [
        TextDelta("Hol"),
        TextDelta("a"),
        ToolCallRequested(ToolCall("c9", "capacidades", "{}")),
        LLMCompleted(input_tokens=10, cached_tokens=8, output_tokens=3),
    ]


async def test_http_error_becomes_llm_error() -> None:
    provider = _provider(httpx.MockTransport(lambda r: httpx.Response(429, text="rate limit")))
    with pytest.raises(LLMError, match="429"):
        _ = [e async for e in provider.stream(LLMRequest(system="s", messages=[]))]
    await provider.aclose()


async def test_failed_event_becomes_llm_error() -> None:
    body = _sse({"type": "response.failed", "response": {"error": {"message": "boom"}}})
    provider = _provider(httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    with pytest.raises(LLMError, match="boom"):
        _ = [e async for e in provider.stream(LLMRequest(system="s", messages=[]))]
    await provider.aclose()


async def test_rate_limit_is_retried() -> None:
    """Fallo real: con muchas preguntas seguidas, un 429 se convertía en «problema técnico»."""
    calls = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, text="rate limit")
        return httpx.Response(200, content=_sse({"type": "response.output_text.delta", "delta": "ok"}))

    provider = _provider(httpx.MockTransport(handle))
    events = [e async for e in provider.stream(LLMRequest(system="s", messages=[]))]
    await provider.aclose()
    assert events == [TextDelta("ok")] and calls["n"] == 2


async def test_web_search_is_dropped_if_the_provider_rejects_it() -> None:
    bodies: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if any(t.get("type") == "web_search" for t in body.get("tools", [])):
            return httpx.Response(400, text='{"error": "tool type web_search is not supported"}')
        return httpx.Response(200, content=_sse({"type": "response.output_text.delta", "delta": "hola"}))

    provider = OpenAIResponsesProvider(
        api_key="k",
        model="m",
        base_url="https://llm.test/v1",
        timeout_seconds=5,
        transport=httpx.MockTransport(handle),
        web_search=True,
    )
    first = [e async for e in provider.stream(LLMRequest(system="s", messages=[]))]
    second = [e async for e in provider.stream(LLMRequest(system="s", messages=[]))]
    await provider.aclose()
    assert first == second == [TextDelta("hola")]
    assert len(bodies) == 3  # rechazo + reintento con el nombre alternativo + segunda petición con él
    assert bodies[1]["tools"] == [{"type": "web_search_preview"}] and bodies[2]["tools"] == [
        {"type": "web_search_preview"}
    ]


async def test_web_sources_are_cited_links_without_tracking_or_unsafe_schemes() -> None:
    """Las consultas externas deben poder verse en su origen: se leen las citas del texto y se limpian los enlaces."""
    from mia.llm import WebSources  # noqa: PLC0415

    def handle(request: httpx.Request) -> httpx.Response:
        body = _sse(
            {"type": "response.output_text.delta", "delta": "Madrid"},
            {
                "type": "response.output_text.annotation.added",
                "annotation": {
                    "type": "url_citation",
                    "url": "https://www.ejemplo.es/nota?utm_source=openai",
                    "title": "Nota",
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "content": [
                        {
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://www.ejemplo.es/nota?utm_source=openai",
                                    "title": "Nota",
                                },
                                {"type": "url_citation", "url": "javascript:alert(1)", "title": "Malo"},
                                {
                                    "type": "url_citation",
                                    "url": "https://otra.org/a?id=7&utm_source=openai",
                                    "title": "Otra",
                                },
                            ]
                        }
                    ],
                },
            },
            {"type": "response.completed", "response": {"output": [], "usage": {}}},
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = _provider(httpx.MockTransport(handle))
    events = [e async for e in provider.stream(LLMRequest(system="s", messages=[Message("user", "x")]))]
    await provider.aclose()
    found = [s for e in events if isinstance(e, WebSources) for s in e.sources]
    assert {"url": "https://www.ejemplo.es/nota", "title": "Nota"} in found
    assert {"url": "https://otra.org/a?id=7", "title": "Otra"} in found
    assert all(s["url"].startswith("https://") for s in found)  # el enlace javascript: se descarta


def test_consulted_sources_are_used_only_when_nothing_is_cited() -> None:
    from mia.llm.openai_responses import extract_web_sources  # noqa: PLC0415

    searched = {"type": "web_search_call", "action": {"sources": [{"url": "https://a.org/x", "title": "A"}]}}
    assert extract_web_sources([searched]) == ({"url": "https://a.org/x", "title": "A"},)
    cited = {
        "type": "message",
        "content": [{"annotations": [{"type": "url_citation", "url": "https://b.org", "title": "B"}]}],
    }
    assert [s["url"] for s in extract_web_sources([searched, cited])] == ["https://b.org"]
