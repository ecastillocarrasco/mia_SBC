from __future__ import annotations

from mia.settings import VoiceProviderName, VoiceSettings
from mia.voice.base import NullVoiceProvider
from mia.voice.cache import CachedVoice
from mia.voice.elevenlabs import ElevenLabsVoiceProvider


def build_voice(settings: VoiceSettings) -> CachedVoice:
    if settings.provider is VoiceProviderName.ELEVENLABS:
        return CachedVoice(ElevenLabsVoiceProvider(settings), max_entries=settings.cache_entries)
    return CachedVoice(NullVoiceProvider(), max_entries=settings.cache_entries)
