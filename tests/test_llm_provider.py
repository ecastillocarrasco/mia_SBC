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
