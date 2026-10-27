"""Diagnostico local de Presidio sobre mIA chat, sin red y sin escritura en BD.

Instalar como tools/mia_validar_presidio_chat.py en el backend de mIA.
Ejecutar con .venv, PYTHONPATH=src. No expone datos reales ni claves.
"""

from __future__ import annotations

import asyncio
import json
import re
from uuid import uuid4

from mia.llm.base import LLMCompleted, LLMRequest, Message, TextDelta, ToolCall, ToolCallRequested
from mia.llm.fake import FakeLLMProvider
from mia.privacy_gateway.context_manager import set_operation_context
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.settings import get_settings

# Datos sinteticos deliberadamente ficticios: no copiar ejemplos reales.
NOMBRE = "María García López"
DNI = "12345678Z"
EMAIL = "prueba@example.com"
IBAN = "ES9121000418450200051332"
PERSON_TOKEN = re.compile(r"\[PERSON_\d{3,}\]")


def redacted(text: str) -> bool:
    return all(value not in text for value in (NOMBRE, DNI, EMAIL, IBAN))


async def collect(gateway: PrivacyGateway, request: LLMRequest):
    return [event async for event in gateway.stream(request)]


async def main() -> None:
    s = get_settings()
    if not s.privacy_gateway.enabled or s.privacy_gateway.fail_open:
        raise SystemExit("BLOQUEADO: gateway desactivado o fail_open activo")
    if not s.privacy_gateway.vault_key.get_secret_value():
        raise SystemExit("BLOQUEADO: Token Vault sin clave propia")

    # Prueba A: captura el texto EXACTAMENTE al otro lado del PrivacyGateway.
    # El proveedor es simulado: no existe conexion a OpenAI.
    def echo_script(req: LLMRequest):
        token = PERSON_TOKEN.search(req.messages[0].content)
        content = "Respuesta de prueba " + (token.group(0) if token else "SIN_TOKEN")
        # Emula un streaming con un token dividido entre varios fragmentos.
        return [*[TextDelta(content[i : i + 4]) for i in range(0, len(content), 4)], LLMCompleted()]

    fake = FakeLLMProvider(script=echo_script)
    gateway = PrivacyGateway(fake, s.privacy_gateway, provider_name="fake", model="test")
    chat_op = uuid4().hex
    set_operation_context(user_id="prueba-local", operation_id=chat_op)
    request = LLMRequest(
        system="No divulges informacion de caracter personal.",
        messages=[
            Message(
                role="user",
                content=(
                    f"Ejemplo ficticio: {NOMBRE}, DNI {DNI}, email {EMAIL}, "
                    f"IBAN {IBAN}. Explica los tipos de datos, sin consultarlos."
                ),
            )
        ],
    )
    response = await collect(gateway, request)
    if not fake.requests:
        raise RuntimeError("El proveedor simulado no recibio la peticion")
    outbound = fake.requests[-1].system + "\n" + "\n".join(m.content for m in fake.requests[-1].messages)
    final_text = "".join(e.text for e in response if isinstance(e, TextDelta))
    chat_protegido = redacted(outbound)
    token_presente = PERSON_TOKEN.search(outbound) is not None
    token = PERSON_TOKEN.search(outbound)
    expected = ""
    if token is not None and gateway._tokenizer is not None:
        expected, _ = gateway._tokenizer.restore(token.group(0), user_id="prueba-local", operation_id=chat_op)
    restauracion_ok = bool(expected) and expected in final_text and "[PERSON_" not in final_text

    print("CHAT: identificadores protegidos antes del proveedor:", chat_protegido)
    print("CHAT: token PERSON enviado al proveedor:", token_presente)
    print("CHAT: respuesta restaurada localmente:", restauracion_ok)

    # Prueba B: el resultado de una herramienta no debe salir con identificadores originales.
    fake_tool = FakeLLMProvider(script=lambda req: [TextDelta("OK"), LLMCompleted()])
    gateway_tool = PrivacyGateway(fake_tool, s.privacy_gateway, provider_name="fake", model="test")
    set_operation_context(user_id="prueba-local", operation_id=uuid4().hex)
    await collect(
        gateway_tool,
        LLMRequest(
            system="Prueba.",
            messages=[
                Message(
                    role="tool",
                    content=json.dumps(
                        {"nombre": NOMBRE, "dni": DNI, "email": EMAIL, "iban": IBAN, "departamento": "Cocina"},
                        ensure_ascii=False,
                    ),
                    tool_call_id="call_test",
                )
            ],
        ),
    )
    tool_outbound = "\n".join(m.content for m in fake_tool.requests[-1].messages)
    tool_protegida = redacted(tool_outbound)
    print("HERRAMIENTA: resultado protegido antes del proveedor:", tool_protegida)

    # Prueba C: detecta si los pseudo-tokens se restauran al RECIBIR argumentos
    # de herramientas. No ejecuta la herramienta; solo inspecciona ese contrato.
    def tool_call_script(req: LLMRequest):
        match = PERSON_TOKEN.search(req.messages[0].content)
        who = match.group(0) if match else "SIN_TOKEN"
        return [
            ToolCallRequested(
                ToolCall(
                    call_id="call_test",
                    name="buscar_empleado_prueba",
                    arguments=json.dumps({"nombre": who}, ensure_ascii=False),
                )
            ),
            LLMCompleted(),
        ]

    fake_call = FakeLLMProvider(script=tool_call_script)
    gateway_call = PrivacyGateway(fake_call, s.privacy_gateway, provider_name="fake", model="test")
    set_operation_context(user_id="prueba-local", operation_id=uuid4().hex)
    events = await collect(
        gateway_call,
        LLMRequest(
            system="Prueba de argumentos; no ejecutes ninguna herramienta real.",
            messages=[Message(role="user", content=f"Busca a {NOMBRE}.")],
        ),
    )
    calls = [e.call for e in events if isinstance(e, ToolCallRequested)]
    arguments = calls[0].arguments if calls else ""
    call_restored = NOMBRE in arguments
    pending_token = PERSON_TOKEN.search(arguments) is not None
    print("HERRAMIENTA: argumentos restaurados para ejecucion:", call_restored)
    print("HERRAMIENTA: persisten tokens al ejecutar:", pending_token)

    print("CONTACTOS_EXTERNOS: NINGUNO (solo FakeLLMProvider)")
    print("ESCRITURAS_POSTGRESQL: NINGUNA")
    if not (chat_protegido and token_presente and restauracion_ok and tool_protegida):
        raise SystemExit("RESULTADO: FALLA prueba basica; no reanudar indexacion sensible")
    if pending_token:
        print("RESULTADO: CHAT PROTEGIDO; CORREGIR restauracion de argumentos antes de consultas por persona")
    elif call_restored:
        print("RESULTADO: CHAT y argumentos restaurados en prueba sintetica")
    else:
        print("RESULTADO: REVISAR contrato de argumentos de herramientas")


if __name__ == "__main__":
    asyncio.run(main())
