"""Ajuste 5 de la aprobación condicionada del Bloque I: re-verificación, con evidencia (no solo
afirmación), de que el comportamiento fail-closed de producción sigue vigente y de que las rutas
multimodales sin protección siguen bloqueadas explícitamente en vez de servirse sin control.

Antes de este ajuste, ``Settings._fail_closed_in_production()`` (``mia/settings.py``) y
``PrivacyGateway.read_image()`` (``mia/privacy_gateway/gateway.py``) ya implementaban estas garantías,
pero NINGUNA prueba existente las ejercitaba: era una afirmación en el código, no una verificación. Esta
es la primera vez que se comprueba con un test real que una configuración de producción insegura es
rechazada al arrancar, no solo que "debería serlo".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mia.llm.fake import FakeLLMProvider
from mia.privacy_gateway.exceptions import UnsafeContentBlockedError
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.settings import AuthMode, Environment, LLMProviderName, PrivacyGatewaySettings
from tests.conftest import make_settings

# Configuración de producción válida mínima: sirve de línea base para aislar, en cada prueba, el ÚNICO
# campo del Privacy Gateway que se quiere comprobar (en vez de arrastrar fallos de otros validadores).
_VALID_PRODUCTION_BASE: dict[str, object] = {
    "environment": Environment.PRODUCTION,
    "auth": {"mode": AuthMode.EASYAUTH},
    "llm": {"provider": LLMProviderName.OPENAI},
    "data": {"pseudonym_key": "clave-real-desde-key-vault"},
    "privacy_gateway": {"enabled": True, "fail_open": False, "vault_key": "clave-real-desde-key-vault"},
}


def _production(tmp_path: Path, **pg_overrides: object) -> dict[str, object]:
    pg = {**_VALID_PRODUCTION_BASE["privacy_gateway"], **pg_overrides}  # type: ignore[dict-item]
    return {**_VALID_PRODUCTION_BASE, "privacy_gateway": pg}


def test_valid_production_configuration_with_gateway_enabled_is_accepted(tmp_path: Path) -> None:
    """Control: una configuración de producción correcta arranca sin error — las pruebas siguientes
    demuestran que CADA desviación concreta, y no la configuración en conjunto, es lo que la bloquea."""
    settings = make_settings(tmp_path, **_production(tmp_path))
    assert settings.privacy_gateway.enabled is True
    assert settings.privacy_gateway.fail_open is False


def test_privacy_gateway_disabled_is_forbidden_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no está permitido en producción"):
        make_settings(tmp_path, **_production(tmp_path, enabled=False))


def test_privacy_gateway_fail_open_is_forbidden_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no está permitido en producción"):
        make_settings(tmp_path, **_production(tmp_path, fail_open=True))


def test_privacy_gateway_without_vault_key_is_forbidden_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="debe venir de Key Vault"):
        make_settings(tmp_path, **_production(tmp_path, vault_key=""))


# --------------------------------------------------------------- rutas multimodales sin protección
async def test_image_reading_is_blocked_while_pixel_content_has_no_protection() -> None:
    """``PrivacyGateway`` solo protege texto hoy (ver docstring de ``read_image``): en vez de servir
    contenido de imagen sin ningún control, la ruta se bloquea explícitamente mientras esa cobertura
    esté pendiente — nunca un bypass silencioso."""
    fake = FakeLLMProvider()
    gateway = PrivacyGateway(
        fake,
        PrivacyGatewaySettings(enabled=True, vault_key="clave-de-prueba-no-real", vault_ttl_seconds=60),
        provider_name="test",
        model="test-model",
    )
    with pytest.raises(UnsafeContentBlockedError):
        await gateway.read_image(b"contenido-binario-de-prueba", "image/png", "describe esta imagen")
    assert fake.requests == []  # nunca llegó a reenviarse hacia el proveedor real


async def test_image_reading_passes_through_when_gateway_disabled() -> None:
    """Control: con el gateway desactivado (``enabled=False``, el valor por defecto fuera de
    producción), la ruta de imagen sigue funcionando sin cambios — el bloqueo es una decisión explícita
    de la Etapa de protección multimodal, no un error que rompa la función existente."""
    fake = FakeLLMProvider()
    gateway = PrivacyGateway(fake, PrivacyGatewaySettings(enabled=False), provider_name="test", model="test-model")
    text = await gateway.read_image(b"contenido-binario-de-prueba", "image/png", "describe esta imagen")
    assert text  # delega en el proveedor real (FakeLLMProvider.read_image), sin bloqueo
