from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class VoiceError(Exception):
    """Fallo del proveedor de voz. La conversación continúa sin audio."""


class VoiceProvider(Protocol):
    media_type: str
    cache_key_prefix: str

    def stream(self, text: str) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


class NullVoiceProvider:
    media_type = "audio/mpeg"
    cache_key_prefix = "none"

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        raise VoiceError("La voz no está configurada")
        yield b""  # pragma: no cover  (convierte la función en generador)

    async def aclose(self) -> None:
        return None
