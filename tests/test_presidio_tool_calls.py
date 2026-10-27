"""Regresion: restauracion local de argumentos y proteccion de rondas sucesivas.

Ejecutar en proyecto: python -m pytest tests/test_presidio_tool_calls.py -q
Los tests usan FakeLLMProvider; no usan PostgreSQL ni OpenAI.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mia.llm.base import LLMCompleted, LLMRequest, Message, TextDelta, ToolCall, ToolCallRequested
from mia.llm.fake import FakeLLMProvider
from mia.privacy_gateway.context_manager import set_operation_context
from mia.privacy_gateway.exceptions import UnsafeContentBlockedError
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.privacy_gateway.token_vault import TokenVault
from mia.settings import PrivacyGatewaySettings

NAME_A = "María García López"
NAME_B = "Laura Pérez Díaz"


def fake_gateway(monkeypatch, script):
    # Test unitario de integración: sustituye solo el detector NLP por uno determinista
    # para evitar dependencias del modelo spaCy y mantener la prueba rápida y estable.
    from mia.privacy_gateway import gateway as gateway_module
    from mia.privacy_gateway.presidio_engine import DetectedEntity

    class Detector:
        def analyze(self, text):
            items = []
            for person in (NAME_A, NAME_B):
                if person in text:
                    i = text.index(person)
                    items.append(DetectedEntity("PERSON", i, i + len(person), 0.99, person))
            return items

    monkeypatch.setattr(gateway_module, "get_presidio_engine", lambda _: Detector())
    settings = PrivacyGatewaySettings(
        enabled=True, fail_open=False, default_policy="standard", vault_key="test-only-key-private-123456"
    )
    inner = FakeLLMProvider(script=script)
    return PrivacyGateway(inner, settings, provider_name="fake", model="fake"), inner


@pytest.mark.asyncio
async def test_inbound_toolcall_restored_and_outbound_history_reprotected(monkeypatch):
    def script(request):
        if len(request.messages) == 1:
            assert NAME_A not in request.messages[0].content
            return [
                ToolCallRequested(
                    ToolCall(
                        "call-1",
                        "buscar_empleado",
                        json.dumps({"nombre": "[PERSON_001]", "extra": ["Cocina", "[PERSON_001]"], "n": 3}),
                    )
                ),
                LLMCompleted(),
            ]
        assert NAME_A not in request.messages[1].tool_calls[0].arguments
        assert "[PERSON_001]" in request.messages[1].tool_calls[0].arguments
        assert NAME_A not in request.messages[2].content
        return [TextDelta("Correcto"), LLMCompleted()]

    gateway, _ = fake_gateway(monkeypatch, script)
    set_operation_context(user_id="usuario_A", operation_id="op-A")
    request = LLMRequest(system="Prueba", messages=[Message(role="user", content=f"Busca {NAME_A}")])
    events = [e async for e in gateway.stream(request)]
    call = next(e.call for e in events if isinstance(e, ToolCallRequested))
    args = json.loads(call.arguments)
    assert args == {"nombre": NAME_A, "extra": ["Cocina", NAME_A], "n": 3}
    # El motor conversacional guarda el argumento restaurado en Message(role='assistant')
    # y el resultado de la herramienta en Message(role='tool'). El gateway protege AMBOS.
    messages = [
        request.messages[0],
        Message(role="assistant", tool_calls=(call,)),
        Message(role="tool", tool_call_id="call-1", content=json.dumps({"nombre": NAME_A})),
    ]
    assert any(isinstance(e, TextDelta) for e in [e async for e in gateway.stream(replace(request, messages=messages))])


@pytest.mark.asyncio
async def test_json_escape_preserves_name_and_structure(monkeypatch):
    gateway, _ = fake_gateway(monkeypatch, lambda request: [LLMCompleted()])
    # Un JSON válido con nombre conteniendo comillas o saltos de línea debe seguir válido.
    gateway._tokenizer._vault.store("PERSON_001", 'María "Ana"\nGarcía', user_id="u", operation_id="o")
    call = ToolCall("1", "buscar", json.dumps({"nombre": "[PERSON_001]", "pags": [1, 2], "extra": {"ok": True}}))
    restored, count = gateway._restore_tool_call(call, user_id="u", operation_id="o")
    assert json.loads(restored.arguments)["nombre"] == 'María "Ana"\nGarcía'
    assert json.loads(restored.arguments)["extra"]["ok"] is True
    assert count == 1


@pytest.mark.asyncio
async def test_foreign_or_expired_token_cannot_execute(monkeypatch):
    gateway, _ = fake_gateway(
        monkeypatch,
        lambda request: [
            ToolCallRequested(ToolCall("c1", "buscar", '{"nombre":"[PERSON_001]"}')),
            LLMCompleted(),
        ],
    )
    set_operation_context(user_id="otro", operation_id="otra-op")
    with pytest.raises(UnsafeContentBlockedError):
        _ = [e async for e in gateway.stream(LLMRequest(system="x", messages=[Message(role="user", content="hola")]))]


def test_vault_parallel_operations_isolated():
    vault = TokenVault("test-only-key-123", 900)
    vault.store("PERSON_001", NAME_A, user_id="a", operation_id="turno1")
    vault.store("PERSON_001", NAME_B, user_id="b", operation_id="turno2")
    assert vault.resolve("PERSON_001", user_id="a", operation_id="turno1") == NAME_A
    assert vault.resolve("PERSON_001", user_id="b", operation_id="turno2") == NAME_B
    assert vault.resolve("PERSON_001", user_id="a", operation_id="turno2") is None
    vault.purge_operation("turno1")
    assert vault.resolve("PERSON_001", user_id="b", operation_id="turno2") == NAME_B
    assert len(vault) == 1
    vault.purge_expired()


@pytest.mark.asyncio
async def test_outbound_token_restored_even_without_brackets(monkeypatch):
    """Regresión: el LLM a veces redacta la frase final citando el identificador sin corchetes
    (p. ej. "PERSON_001" en vez de "[PERSON_001]"); el token debe restaurarse igual, no filtrarse
    en crudo al usuario."""
    gateway, _ = fake_gateway(
        monkeypatch,
        lambda request: [
            TextDelta("No he encontrado a nadie con el nombre 'PERSON_001'."),
            LLMCompleted(),
        ],
    )
    gateway._tokenizer._vault.store("PERSON_001", NAME_A, user_id="u", operation_id="o")
    set_operation_context(user_id="u", operation_id="o")
    events = [e async for e in gateway.stream(LLMRequest(system="x", messages=[Message(role="user", content="hola")]))]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert NAME_A in text
    assert "PERSON_001" not in text


@pytest.mark.asyncio
async def test_business_identifier_with_token_like_shape_is_left_untouched(monkeypatch):
    """Un identificador de negocio real con la misma forma (MAYUSCULAS_NNN) pero que no es un tipo
    de entidad protegido (ni está en el vault) no debe tocarse ni bloquear la respuesta."""
    gateway, _ = fake_gateway(
        monkeypatch,
        lambda request: [
            TextDelta("La factura FACTURA_045 está pendiente de pago."),
            LLMCompleted(),
        ],
    )
    set_operation_context(user_id="u", operation_id="o")
    events = [e async for e in gateway.stream(LLMRequest(system="x", messages=[Message(role="user", content="hola")]))]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "FACTURA_045" in text


@pytest.mark.asyncio
async def test_disabled_gateway_pass_through(monkeypatch):
    from mia.privacy_gateway import gateway as gateway_module

    monkeypatch.setattr(gateway_module, "get_presidio_engine", lambda _: None)
    settings = PrivacyGatewaySettings(enabled=False)
    original = ToolCall("c1", "buscar", json.dumps({"nombre": NAME_A}))
    provider = FakeLLMProvider(script=lambda req: [ToolCallRequested(original), LLMCompleted()])
    gateway = PrivacyGateway(provider, settings, provider_name="fake", model="fake")
    events = [e async for e in gateway.stream(LLMRequest(system="x", messages=[]))]
    assert events[0].call == original
