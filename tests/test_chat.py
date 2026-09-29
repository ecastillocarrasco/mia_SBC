from __future__ import annotations

import json

import httpx
from pydantic import BaseModel
from sqlalchemy import func, select

from mia.api.services import Services
from mia.conversation import Tool, ToolContext, ToolResult
from mia.data import AuditEvent, ConversationTurn
from mia.llm import LLMError
from mia.llm.base import LLMRequest
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from tests.conftest import Script


def _sse_events(body: str) -> list[dict[str, object]]:
    events = []
    for block in body.strip().split("\n\n"):
        data = next(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
        events.append(json.loads(data))
    return events


async def test_chat_returns_structured_answer(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/chat", json={"message": "Hola"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Hola, soy mIA."
    assert body["speech"].startswith("¡Hola!")
    assert body["avatar_state"] == "saludando"
    assert len(body["session_id"]) == 32


async def test_session_history_is_server_side(client: httpx.AsyncClient, services: Services) -> None:
    first = (await client.post("/api/chat", json={"message": "Primera"})).json()
    await client.post("/api/chat", json={"message": "Segunda", "session_id": first["session_id"]})

    llm = services.llm
    assert isinstance(llm, FakeLLMProvider)
    second_request = llm.requests[-1]
    contents = [m.content.split("\n\n<contexto_del_turno>")[0] for m in second_request.messages]
    assert contents == ["Primera", "Hola, soy mIA.", "Segunda"]

    async with services.db.session() as db:
        count = await db.scalar(select(func.count()).select_from(ConversationTurn))
    assert count == 4


async def test_invalid_avatar_state_falls_back(client: httpx.AsyncClient, script: list[Script]) -> None:
    script[0] = lambda req: final_answer("Texto", "Voz", "bailando")
    body = (await client.post("/api/chat", json={"message": "x"})).json()
    assert body["avatar_state"] == "hablando"


async def test_tool_flow_streams_filler_then_answer(client: httpx.AsyncClient, script: list[Script]) -> None:
    def scripted(req: LLMRequest) -> list:  # type: ignore[type-arg]
        if req.messages[-1].role == "tool":
            return final_answer("Aún estoy migrando los datos de RRHH.", "Todavía estoy migrando esos datos. Pronto.")
        return tool_call("capacidades", {})

    script[0] = scripted
    response = await client.post("/api/chat/stream", json={"message": "¿Qué sabes hacer?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session"
    assert kinds[-1] == "result"

    speech = [e for e in events if e["type"] == "speech"]
    assert speech[0]["filler"] is True
    assert kinds.index("speech") < kinds.index("tool")
    assert [s["text"] for s in speech[1:]] == ["Todavía estoy migrando esos datos.", "Pronto."]

    result = events[-1]["result"]
    assert isinstance(result, dict)
    assert result["tools"][0]["name"] == "capacidades"
    assert result["tools"][0]["status"] == "ok"


async def test_llm_failure_returns_graceful_error(client: httpx.AsyncClient, script: list[Script]) -> None:

    def failing(req: LLMRequest) -> list:  # type: ignore[type-arg]
        raise LLMError("sin cuota")

    script[0] = failing
    body = (await client.post("/api/chat", json={"message": "hola"})).json()
    assert body["status"] == "error"
    assert body["avatar_state"] == "confundida"


async def test_audited_tool_leaves_trace(client: httpx.AsyncClient, services: Services, script: list[Script]) -> None:

    class Params(BaseModel):
        nombre: str

    async def handler(params: Params, ctx: ToolContext) -> ToolResult:
        return ToolResult.ok({"encontrado": params.nombre}, {"type": "ficha"})

    services.engine._tools.register(Tool("ficha_prueba", "Prueba", Params, handler, audit_resource="empleados"))

    def scripted(req: LLMRequest) -> list:  # type: ignore[type-arg]
        if req.messages[-1].role == "tool":
            return final_answer("Aquí la tienes.", "Aquí tienes la ficha.")
        return tool_call("ficha_prueba", {"nombre": "Ana"})

    script[0] = scripted
    body = (await client.post("/api/chat", json={"message": "Ficha de Ana"})).json()
    assert body["presentations"] == [{"type": "ficha"}]

    async with services.db.session() as db:
        events = list((await db.scalars(select(AuditEvent))).all())
    assert len(events) == 1
    assert events[0].resource == "empleados"
    assert events[0].detail == {"arguments": {"nombre": "Ana"}}
    assert events[0].user_id == "dev-user"


def test_answer_with_real_newlines_inside_json_strings_is_still_parsed() -> None:
    """Fallo real: al citar fuentes web el proveedor mete saltos de línea reales dentro del JSON; se veía en bruto."""
    from mia.conversation.engine import parse_final_answer  # noqa: PLC0415

    raw = (
        '{"habla":"Mañana en Málaga habrá sol, entre 21 y 27 grados.","estado_avatar":"reposo",'
        '"texto":"Mañana en Málaga: **sol**, entre 21 °C y 27 °C.\n\n([Málaga, España](https://www.google.com/x?utm_source=openai))"}'
    )
    answer = parse_final_answer(raw)
    assert answer.text == "Mañana en Málaga: **sol**, entre 21 °C y 27 °C."  # la cita la muestra la pantalla
    assert answer.speech == "Mañana en Málaga habrá sol, entre 21 y 27 grados."
    assert answer.avatar_state == "reposo"


def test_broken_json_is_never_spoken_or_shown_as_such() -> None:
    from mia.conversation.engine import NEUTRAL_SPEECH, parse_final_answer  # noqa: PLC0415

    answer = parse_final_answer('{"habla":"Hola","texto":"Cosas" ')  # JSON cortado
    assert answer.text == "Cosas" and answer.speech == "Hola"
    garbage = parse_final_answer("{esto no es json}")
    assert garbage.speech == NEUTRAL_SPEECH  # nunca se locuta un JSON roto


def test_inbox_questions_get_a_hint_but_employee_email_questions_do_not() -> None:
    """Fallo real: «resumen de mis últimos 10 correos sin leer» se tomó por una búsqueda del empleado «Enrique»."""
    from datetime import datetime  # noqa: PLC0415

    from mia.conversation.persona import Persona  # noqa: PLC0415

    persona, mailbox = Persona(), "nominas@sunsetbeachclub.com"
    for message in ("Resumen de mis últimos 10 correos sin leer", "¿Tengo correos nuevos?", "resume mi bandeja"):
        assert mailbox in persona.hint_for(message, mailbox)
    assert persona.hint_for("¿Cuál es el email de Sandra Asencio?", mailbox) == ""
    assert persona.hint_for("mis correos sin leer", "") == ""  # sin buzón no hay pista
    context = persona.turn_context(
        user_name="Enrique", now=datetime.now(), mailbox=mailbox, hint=persona.hint_for("mis correos", mailbox)
    )
    assert f"el buzón de esta conversación es {mailbox}" in context and "Pista para este mensaje" in context


def test_the_fixed_prompt_is_identical_between_turns_so_the_provider_can_cache_it() -> None:
    """Caso real: 23.000 tokens de entrada por pregunta y tokens_cached=0; la hora al inicio rompía la caché."""
    import os  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415

    from mia.conversation.persona import Persona  # noqa: PLC0415

    persona = Persona()
    fixed = persona.system_prompt(business_rules=["R1 regla"], capabilities="- capacidad")
    again = persona.system_prompt(business_rules=["R1 regla"], capabilities="- capacidad")
    assert fixed == again  # nada dependiente del usuario, la hora o el foco
    one = persona.turn_context(user_name="Marisol", now=datetime(2026, 9, 29, 10, 0), focus="Persona: A")
    two = persona.turn_context(user_name="Luis", now=datetime(2026, 9, 29, 10, 1), mailbox="x@y.z", hint="\n\nPista")
    assert one != two and "Marisol" in one and "Marisol" not in fixed and "10:00" not in fixed
    assert len(os.path.commonprefix([fixed + one, fixed + two])) >= len(fixed)
