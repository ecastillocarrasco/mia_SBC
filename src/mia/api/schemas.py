from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=32)
    attachment_ids: list[str] | None = Field(default=None, max_length=10)


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class WelcomeResponse(BaseModel):
    text: str


class MemorySettingsResponse(BaseModel):
    available: bool
    """Si la Memoria Inteligente está activada globalmente en este despliegue
    (``MIA_MEMORY__ENABLED``). Con ``False``, ``enabled`` no tiene sentido y el frontend debe
    ocultar el control por completo, no mostrarlo deshabilitado."""
    enabled: bool
    """Interruptor propio del usuario (independiente del global), desactivado por defecto."""


class MemorySettingsUpdate(BaseModel):
    enabled: bool


class MemoryItem(BaseModel):
    id: str
    content: str = Field(max_length=500)
    created_at: str


class MemoryItemsResponse(BaseModel):
    enabled: bool
    items: list[MemoryItem]


class MemoryDeleteResponse(BaseModel):
    deleted: int
