from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from mia.api.services import Services
from mia.settings import VoiceSettings
from mia.voice import CachedVoice, VoiceError
from mia.voice.elevenlabs import ElevenLabsVoiceProvider


class _CountingVoice:
    media_type = "audio/mpeg"
    cache_key_prefix = "test"

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        self.calls += 1
        yield b"ab"
        yield b"cd"

    async def aclose(self) -> None:
        return None


async def _collect(voice: CachedVoice, text: str) -> bytes:
    return b"".join([chunk async for chunk in voice.stream(text)])


async def test_short_phrases_are_cached() -> None:
    inner = _CountingVoice()
    voice = CachedVoice(inner)
    assert await _collect(voice, "Déjame mirarlo.") == b"abcd"
    assert await _collect(voice, "  déjame   mirarlo. ") == b"abcd"
    assert inner.calls == 1


async def test_long_text_is_not_cached() -> None:
    inner = _CountingVoice()
    voice = CachedVoice(inner, max_chars=10)
    await _collect(voice, "Una frase bastante larga")
    await _collect(voice, "Una frase bastante larga")
    assert inner.calls == 2


def _settings() -> VoiceSettings:
    return VoiceSettings(provider="elevenlabs", api_key=SecretStr("xi"), voice_id="v1")  # type: ignore[arg-type]


async def test_elevenlabs_streams_audio() -> None:
    seen: dict[str, httpx.Request] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["req"] = request
        return httpx.Response(200, content=b"MP3DATA")

    provider = ElevenLabsVoiceProvider(_settings(), transport=httpx.MockTransport(handle))
    audio = b"".join([c async for c in provider.stream("Hola   Enrique")])
    await provider.aclose()
    assert audio == b"MP3DATA"
    assert seen["req"].url.path == "/v1/text-to-speech/v1/stream"
    assert seen["req"].headers["xi-api-key"] == "xi"
    assert b'"Hola Enrique"' in seen["req"].content


async def test_elevenlabs_error_is_voice_error() -> None:
    provider = ElevenLabsVoiceProvider(
        _settings(), transport=httpx.MockTransport(lambda r: httpx.Response(401))
    )
    with pytest.raises(VoiceError):
        _ = [c async for c in provider.stream("Hola")]
    await provider.aclose()


async def test_voice_route_streams_audio(client: httpx.AsyncClient, services: Services) -> None:
    services.voice = CachedVoice(_CountingVoice())
    for path in ("/api/voice/stream", "/api/mia/voice"):
        response = await client.post(path, json={"text": "Hola"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert response.content == b"abcd"
