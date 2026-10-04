from __future__ import annotations

from mia.llm.base import LLMProvider
from mia.llm.fake import FakeLLMProvider
from mia.llm.openai_responses import OpenAIResponsesProvider
from mia.settings import LLMProviderName, LLMSettings


def build_llm_provider(settings: LLMSettings) -> LLMProvider:
    if settings.provider is LLMProviderName.FAKE:
        return FakeLLMProvider()
    if not settings.api_key.get_secret_value():
        raise ValueError(f"Falta MIA_LLM__API_KEY para el proveedor {settings.provider.value}")
    return OpenAIResponsesProvider(
        api_key=settings.api_key.get_secret_value(),
        model=settings.model,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        azure=settings.provider is LLMProviderName.AZURE_OPENAI,
    )
