"""Texto a voz con ElevenLabs en modo streaming (el audio empieza a sonar al llegar el primer bloque)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from mia.settings import VoiceSettings
from mia.voice.base import VoiceError


class ElevenLabsVoiceProvider:
    media_type = "audio/mpeg"

    def __init__(self, settings: VoiceSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not settings.api_key.get_secret_value() or not settings.voice_id:
            raise ValueError("ElevenLabs requiere MIA_VOICE__API_KEY y MIA_VOICE__VOICE_ID")
        self._settings = settings
        self.cache_key_prefix = f"elevenlabs:{settings.voice_id}:{settings.model_id}:{settings.output_format}"
        self._client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            headers={"xi-api-key": settings.api_key.get_secret_value(), "Accept": self.media_type},
            timeout=httpx.Timeout(settings.timeout_seconds, connect=5.0),
            transport=transport,
        )

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        clean = " ".join(text.split())[: self._settings.max_chars]
        if not clean:
            return
        url = f"/text-to-speech/{self._settings.voice_id}/stream"
        body = {"text": clean, "model_id": self._settings.model_id}
        params = {"output_format": self._settings.output_format}
        try:
            async with self._client.stream("POST", url, json=body, params=params) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")[:300]
                    raise VoiceError(f"ElevenLabs HTTP {response.status_code}: {detail}")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise VoiceError(f"Error de red con ElevenLabs: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
