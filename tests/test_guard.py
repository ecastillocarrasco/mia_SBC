from __future__ import annotations

import re

import httpx
from tools.eval_conversation import claims_capability

from mia.conversation import guard
from mia.llm.fake import final_answer
from tests.conftest import Script

CLAIMS_TURNOS = claims_capability("turnos")


def test_removes_only_the_promise_sentence() -> None:
    text = "La consulta de turnos está en migración. Te avisaré en cuanto esté disponible."
    assert guard.clean(text) == "La consulta de turnos está en migración."


def test_variants_are_blocked() -> None:
    for phrase in (
        "Te lo haré saber pronto.",
        "Te informaré cuando esté listo.",
        "Me pondré en contacto contigo.",
        "Te mantendré informado.",
        "Volveré a escribirte mañana.",
    ):
        assert guard.is_blocked(phrase), phrase


def test_normal_text_is_untouched() -> None:
    text = "Todavía no está disponible; pregúntame más adelante.\n- Punto uno. Punto dos."
    assert guard.clean(text) == text


async def test_engine_never_says_or_shows_the_promise(
    client: httpx.AsyncClient, script: list[Script]
) -> None:
    script[0] = lambda req: final_answer(
        "Aún no está disponible. Te avisaré cuando lo esté.",
        "Aún no puedo consultarlo. Te avisaré en cuanto pueda.",
    )
    stream = (await client.post("/api/chat/stream", json={"message": "¿turnos?"})).text
    assert "avisar" not in stream.lower()
    body = (await client.post("/api/chat", json={"message": "¿turnos?"})).json()
    assert body["answer"] == "Aún no está disponible."
    assert body["speech"] == "Aún no puedo consultarlo."


def test_eval_pattern_ignores_negations() -> None:
    assert re.search(CLAIMS_TURNOS, "Ya puedo consultar los turnos", re.I)
    assert not re.search(CLAIMS_TURNOS, "Todavía no puedo consultar los turnos de Ana", re.I)
    assert not re.search(CLAIMS_TURNOS, "Aún no puedo consultar turnos", re.I)


def test_amounts_are_never_spoken() -> None:
    assert guard.speech_blocked("Su líquido fue de 1.234,56 €.")
    assert guard.speech_blocked("Cobró 980 euros.")
    assert not guard.speech_blocked("Tiene 3 nóminas sin leer.")
    assert (
        guard.clean_speech("Ya la tengo. El líquido es 1.234,56 €. Te lo muestro.")
        == "Ya la tengo. Te lo muestro."
    )
