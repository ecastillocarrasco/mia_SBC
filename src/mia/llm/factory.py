from __future__ import annotations

from mia.llm.base import LLMProvider
from mia.llm.fake import FakeLLMProvider
from mia.llm.openai_responses import OpenAIResponsesProvider
from mia.settings import LLMProviderName, LLMSettings, PrivacyGatewaySettings


def build_llm_provider(
    settings: LLMSettings, privacy_settings: PrivacyGatewaySettings | None = None
) -> LLMProvider:
    """Único punto de construcción de un LLMProvider en todo mIA. SIEMPRE devuelve una instancia
    envuelta en PrivacyGateway — no existe otra forma de obtener un proveedor real, así que ningún
    módulo nuevo puede "olvidarse" de pasar por la protección de privacidad (ver mia.privacy_gateway).

    Import perezoso de PrivacyGateway (no al nivel de módulo): mia.privacy_gateway.gateway importa
    tipos de mia.llm.base, y cargar el paquete mia.llm siempre dispara mia/llm/__init__.py, que a su
    vez importa este mismo factory.py — un ciclo real si algo importa mia.privacy_gateway primero.
    Diferirlo hasta la llamada rompe el ciclo sin cambiar el comportamiento en tiempo de ejecución."""
    from mia.privacy_gateway.gateway import PrivacyGateway  # noqa: PLC0415

    if settings.provider is LLMProviderName.FAKE:
        inner: LLMProvider = FakeLLMProvider()
    else:
        if not settings.api_key.get_secret_value():
            raise ValueError(f"Falta MIA_LLM__API_KEY para el proveedor {settings.provider.value}")
        inner = OpenAIResponsesProvider(
            api_key=settings.api_key.get_secret_value(),
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            azure=settings.provider is LLMProviderName.AZURE_OPENAI,
            web_search=settings.web_search,
        )
    return PrivacyGateway(
        inner,
        privacy_settings or PrivacyGatewaySettings(),
        provider_name=settings.provider.value,
        model=settings.model,
    )
