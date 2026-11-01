import json

import pytest

from mia.llm.base import LLMRequest, Message, ToolCall
from mia.llm.fake import FakeLLMProvider, final_answer
from mia.privacy_gateway.context_manager import embedding_scope, set_operation_context
from mia.privacy_gateway.economic_minimization import redact_individual_amounts
from mia.privacy_gateway.exceptions import UnsafeContentBlockedError
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.privacy_gateway.policy_engine import Policy
from mia.privacy_gateway.structured_minimization import protect_structured
from mia.settings import PrivacyGatewaySettings


@pytest.mark.parametrize("policy", list(Policy))
def test_nested_individual_amounts_are_reserved_for_every_policy_and_without_ner(policy):
    payload = {
        "persona": "Nombre no detectado",
        "nominas": [
            {
                "periodo": "2026-08",
                "importes": {"liquido": 1234, "irpf_porcentaje": 12},
                "conceptos": {"devengos": [{"importe": "1.234,00", "concepto": "Salario"}]},
            }
        ],
    }
    protected = redact_individual_amounts(json.dumps(payload), policy=policy)
    assert "1234" not in protected and "1.234" not in protected
    assert "2026-08" in protected
    assert payload["nominas"][0]["importes"]["liquido"] == 1234


def test_aggregate_totals_are_preserved_for_analysis():
    payload = {"departamento": "Pruebas", "personas": 20, "total_coste": 40000, "media": 2000}
    assert json.loads(redact_individual_amounts(json.dumps(payload), policy=Policy.STANDARD)) == payload


def test_medical_record_is_reserved_as_a_whole_including_its_category():
    payload = {
        "persona": "Nombre sintético",
        "tipo": "Reconocimiento médico",
        "documento": "archivo_medico.pdf",
        "texto": "Detalle clínico sintético",
        "resultado": "Clasificación privada",
    }
    protected, _ = protect_structured(json.dumps(payload), lambda value, kind: "[PERSON_001]", reserve_content=True)
    assert "Nombre" not in protected and "médico" not in protected and "privada" not in protected
    assert "RESERVADO_EN_MIA" in protected


async def test_structured_identifiers_and_content_are_protected_even_when_ner_detects_nothing(monkeypatch):
    class NoDetections:
        def analyze(self, text):
            return []

    monkeypatch.setattr("mia.privacy_gateway.gateway.get_presidio_engine", lambda model: NoDetections())
    fake = FakeLLMProvider(lambda request: final_answer("Revisado", "Listo"))
    gateway = PrivacyGateway(
        fake, PrivacyGatewaySettings(enabled=True, vault_key="test-key"), provider_name="test", model="test"
    )
    set_operation_context(user_id="synthetic-user", operation_id="structured-test")
    payload = {
        "persona": "QzxNombre984",
        "employee_id": 987654,
        "texto": "DIAGNOSTICO_SINTETICO_984",
        "nominas": [{"importes": {"liquido": 1234}}],
    }
    request = LLMRequest(
        system="Responde",
        messages=[
            Message(
                role="assistant",
                tool_calls=(ToolCall("call", "leer_documento", json.dumps({"nombre": "QzxNombre984", "limite": 3})),),
            ),
            Message(role="tool", tool_call_id="call", content=json.dumps(payload)),
        ],
    )
    async for _ in gateway.stream(request):
        pass
    outgoing = fake.requests[0]
    captured = json.dumps([message.content for message in outgoing.messages])
    assert "QzxNombre984" not in captured and "987654" not in captured
    assert "DIAGNOSTICO_SINTETICO_984" not in captured and "1234" not in captured
    args = json.loads(outgoing.messages[0].tool_calls[0].arguments)
    assert args["nombre"].startswith("[PERSON_") and args["limite"] == 3
    assert payload["texto"] == "DIAGNOSTICO_SINTETICO_984"


async def test_raw_document_embedding_requires_a_reviewed_projection_and_never_falls_back(monkeypatch):
    class NoDetections:
        def analyze(self, text):
            return []

    class RecordingProvider(FakeLLMProvider):
        def __init__(self):
            super().__init__()
            self.embedded = []

        async def embed(self, texts, model):
            self.embedded.extend(texts)
            return [[0.0] for text in texts]

    monkeypatch.setattr("mia.privacy_gateway.gateway.get_presidio_engine", lambda model: NoDetections())
    provider = RecordingProvider()
    gateway = PrivacyGateway(
        provider, PrivacyGatewaySettings(enabled=True, vault_key="test-key"), provider_name="test", model="test"
    )
    with pytest.raises(UnsafeContentBlockedError):
        await gateway.embed(["PRIVATE_SOURCE_984"], "test")
    with embedding_scope("private_source"), pytest.raises(UnsafeContentBlockedError):
        await gateway.embed(["PRIVATE_SOURCE_984"], "test")
    assert provider.embedded == []
    with embedding_scope("minimized_source"):
        await gateway.embed(["Conceptos generales de nómina"], "test")
    with embedding_scope("query"):
        await gateway.embed(["Busca experiencia en cocina"], "test")
    assert provider.embedded == ["Conceptos generales de nómina", "Busca experiencia en cocina"]
