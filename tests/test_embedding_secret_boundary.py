"""Credenciales sintéticas: inspeccionar lo que recibe el proveedor de embeddings."""

import pytest

from mia.llm.fake import FakeLLMProvider
from mia.privacy_gateway.context_manager import embedding_scope
from mia.privacy_gateway.exceptions import UnsafeContentBlockedError
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.settings import PrivacyGatewaySettings


class CapturingProvider(FakeLLMProvider):
    def __init__(self):
        super().__init__()
        self.received = []

    async def embed(self, texts, model):
        self.received.append((texts, model))
        return [[1.0] for _ in texts]


class NoDetections:
    def analyze(self, text):
        return []


@pytest.mark.parametrize("purpose", ["query", "minimized_source"])
@pytest.mark.parametrize(
    "secret",
    [
        "sk-syntheticcredential1234567890",
        "password=synthetic-password",
        "api_key=synthetic-key",
        "-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----",
        "eyJabcdefghijk.abcdefghijklm.abcdefghijklm",
        "postgresql://synthetic:password@example.invalid/db",
    ],
)
async def test_embeddings_remove_secrets_without_ner_detections(monkeypatch, purpose, secret):
    monkeypatch.setattr("mia.privacy_gateway.gateway.get_presidio_engine", lambda model: NoDetections())
    provider = CapturingProvider()
    gateway = PrivacyGateway(
        provider, PrivacyGatewaySettings(enabled=True, vault_key="test-key"), provider_name="test", model="test"
    )
    inputs = [f"Consulta de cocina {secret}", "Consulta de mantenimiento", ""]
    with embedding_scope(purpose):
        vectors = await gateway.embed(inputs, "test-embedding")
    assert provider.received == [
        (["Consulta de cocina [SECRETO_REDACTADO]", "Consulta de mantenimiento", ""], "test-embedding")
    ]
    assert vectors == [[1.0], [1.0], [1.0]]
    assert secret in inputs[0]


async def test_secret_filter_failure_blocks_embedding_provider(monkeypatch):
    monkeypatch.setattr("mia.privacy_gateway.gateway.get_presidio_engine", lambda model: NoDetections())

    def broken_filter(text):
        raise RuntimeError("Synthetic failure")

    monkeypatch.setattr("mia.privacy_gateway.gateway.redact_secrets", broken_filter)
    provider = CapturingProvider()
    gateway = PrivacyGateway(
        provider,
        PrivacyGatewaySettings(enabled=True, vault_key="test-key", fail_open=False),
        provider_name="test",
        model="test",
    )
    with embedding_scope("query"), pytest.raises(UnsafeContentBlockedError):
        await gateway.embed(["password=synthetic-password"], "test-embedding")
    assert provider.received == []
