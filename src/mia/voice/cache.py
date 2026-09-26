"""Caché de audio para frases repetidas (saludos, esperas, avisos).

Las frases fijas se generan una sola vez: suenan al instante y no consumen créditos.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import AsyncIterator

from mia.voice.base import VoiceProvider


class CachedVoice:
    def __init__(self, provider: VoiceProvider, max_entries: int = 256, max_chars: int = 160) -> None:
        self._provider = provider
        self._max_entries = max_entries
        self._max_chars = max_chars
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self.media_type = provider.media_type
        self.cache_key_prefix = provider.cache_key_prefix

    def _key(self, text: str) -> str:
        normalized = " ".join(text.split()).lower()
        return hashlib.sha256(f"{self.cache_key_prefix}|{normalized}".encode()).hexdigest()

    def cached(self, text: str) -> bytes | None:
        key = self._key(text)
        audio = self._entries.get(key)
        if audio is not None:
            self._entries.move_to_end(key)
        return audio

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        hit = self.cached(text)
        if hit is not None:
            yield hit
            return
        cacheable = len(text) <= self._max_chars
        buffer = bytearray()
        async for chunk in self._provider.stream(text):
            if cacheable:
                buffer.extend(chunk)
            yield chunk
        if cacheable and buffer:
            self._entries[self._key(text)] = bytes(buffer)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    async def warm(self, phrases: list[str]) -> int:
        warmed = 0
        for phrase in phrases:
            async for _ in self.stream(phrase):
                pass
            warmed += 1
        return warmed

    async def aclose(self) -> None:
        await self._provider.aclose()
