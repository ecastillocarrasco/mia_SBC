"""Proveedor LLM guionizado para tests y desarrollo sin clave."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from mia.llm.base import LLMCompleted, LLMEvent, LLMRequest, TextDelta, ToolCall, ToolCallRequested
from mia.text import normalize_key

Script = Callable[[LLMRequest], list[LLMEvent]]


def final_answer(texto: str, habla: str, estado_avatar: str = "hablando") -> list[LLMEvent]:
    body = json.dumps({"habla": habla, "estado_avatar": estado_avatar, "texto": texto}, ensure_ascii=False)
    step = 7
    chunks: list[LLMEvent] = [TextDelta(body[i : i + step]) for i in range(0, len(body), step)]
    return [*chunks, LLMCompleted(input_tokens=100, output_tokens=len(body) // 4)]


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> list[LLMEvent]:
    return [ToolCallRequested(ToolCall(call_id, name, json.dumps(arguments))), LLMCompleted()]


def _default_script(request: LLMRequest) -> list[LLMEvent]:
    last = request.messages[-1].content if request.messages else ""
    return final_answer(
        texto=f"Modo de desarrollo sin LLM. He recibido: {last}",
        habla="Estoy en modo de desarrollo, todavía sin modelo conectado.",
        estado_avatar="sonriendo",
    )


class FakeLLMProvider:
    def __init__(self, script: Script | None = None) -> None:
        self._script = script or _default_script
        self.requests: list[LLMRequest] = []

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        for event in self._script(request):
            yield event

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Embeddings deterministas de bolsa de palabras (suficiente para probar la búsqueda)."""
        vectors = []
        for text in texts:
            vector = [0.0] * 64
            for word in normalize_key(text).split():
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0  # noqa: S324
            vectors.append(vector)
        return vectors

    async def read_image(self, content: bytes, media_type: str, instruction: str) -> str:
        return "Texto leído de una imagen: camarera de pisos con experiencia en hoteles de playa y francés."

    async def aclose(self) -> None:
        return None
