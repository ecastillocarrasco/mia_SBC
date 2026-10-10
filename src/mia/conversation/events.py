"""Eventos que emite un turno de conversación (se envían al cliente por SSE)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TurnResult(BaseModel):
    session_id: str
    status: Literal["ok", "error"] = "ok"
    answer: str
    speech: str
    avatar_state: str
    presentations: list[dict[str, Any]] = Field(default_factory=list)
    summaries: list[dict[str, Any]] = Field(default_factory=list)
    """Resumen de cada herramienta (totales, desgloses, avisos): lo mismo que ve el modelo, para la pantalla."""
    web_sources: list[dict[str, str]] = Field(default_factory=list)
    """Fuentes web consultadas por el modelo ({url, title}): la pantalla las muestra como enlaces."""
    tools: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_ms: int = 0
    usage: dict[str, int] = Field(default_factory=dict)
    presentation_intent: str = "direct_lookup"
    """Intención de presentación clasificada para este turno (PresentationIntent value)."""


class SessionEvent(BaseModel):
    type: Literal["session"] = "session"
    session_id: str


class AvatarEvent(BaseModel):
    type: Literal["avatar"] = "avatar"
    state: str


class SpeechEvent(BaseModel):
    type: Literal["speech"] = "speech"
    text: str
    filler: bool = False
    """True para frases de espera mientras se consultan datos."""


class ProgressEvent(BaseModel):
    type: Literal["progress"] = "progress"
    stage: str
    message: str


class ToolEvent(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    status: str
    elapsed_ms: int


class ResultEvent(BaseModel):
    type: Literal["result"] = "result"
    result: TurnResult


TurnEvent = SessionEvent | AvatarEvent | SpeechEvent | ProgressEvent | ToolEvent | ResultEvent
