"""Contrato común para cualquier proveedor LLM.

El resto de mIA solo conoce estos tipos, de modo que cambiar de proveedor
(OpenAI, Azure OpenAI u otro) no afecta a dominios ni conversación.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str
    """JSON tal como lo emite el modelo; lo valida el registro de herramientas."""


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSchema] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    """JSON Schema de la respuesta final (salida estructurada)."""
    max_output_tokens: int = 1200
    model: str | None = None
    """Anula el modelo por defecto del proveedor para ESTA petición (Fase F: niveles FAST/BALANCED/
    ADVANCED, ver ``mia.llm.tiers``). ``None`` conserva el comportamiento anterior a esta fase."""


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallRequested:
    call: ToolCall


@dataclass(frozen=True, slots=True)
class LLMCompleted:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class WebSources:
    """Fuentes web que el proveedor ha citado o consultado en la búsqueda: [{url, title}]."""

    sources: tuple[dict[str, str], ...]


LLMEvent = TextDelta | ToolCallRequested | LLMCompleted | WebSources


class LLMError(Exception):
    """Fallo del proveedor LLM (red, cuota, respuesta inválida)."""


class LLMProvider(Protocol):
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]: ...

    async def embed(self, texts: list[str], model: str) -> list[list[float]]: ...

    async def read_image(self, content: bytes, media_type: str, instruction: str) -> str: ...

    async def aclose(self) -> None: ...
