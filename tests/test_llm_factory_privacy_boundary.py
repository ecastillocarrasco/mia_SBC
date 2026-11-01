from unittest.mock import Mock

import pytest

from mia.llm.factory import build_llm_provider
from mia.settings import LLMProviderName, LLMSettings, PrivacyGatewaySettings


@pytest.mark.parametrize(
    "privacy",
    [
        None,
        PrivacyGatewaySettings(enabled=False),
        PrivacyGatewaySettings(enabled=True, fail_open=True, vault_key="test-key"),
        PrivacyGatewaySettings(enabled=True, fail_open=False),
    ],
)
def test_external_provider_is_not_constructed_without_required_protection(monkeypatch, privacy):
    remote = Mock()
    monkeypatch.setattr("mia.llm.factory.OpenAIResponsesProvider", remote)
    settings = LLMSettings(provider=LLMProviderName.OPENAI, api_key="synthetic-key")
    with pytest.raises(ValueError, match="Privacy Gateway activo"):
        build_llm_provider(settings, privacy)
    remote.assert_not_called()


def test_protected_provider_cannot_search_the_public_web_with_corporate_context(monkeypatch):
    remote = Mock()
    gateway = Mock()
    monkeypatch.setattr("mia.llm.factory.OpenAIResponsesProvider", remote)
    monkeypatch.setattr("mia.privacy_gateway.gateway.PrivacyGateway", gateway)
    settings = LLMSettings(provider=LLMProviderName.OPENAI, api_key="synthetic-key", web_search=True)
    privacy = PrivacyGatewaySettings(enabled=True, fail_open=False, vault_key="test-key")
    assert build_llm_provider(settings, privacy) is gateway.return_value
    assert remote.call_args.kwargs["web_search"] is False
    assert gateway.call_args.args == (remote.return_value, privacy)
