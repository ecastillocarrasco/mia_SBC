"""Evaluación del comportamiento conversacional contra el modelo real.

Uso (con mIA arrancada y un LLM real configurado):
    python tools/eval_conversation.py [--url http://127.0.0.1:5001]

Cada caso es una conversación; se comprueba la respuesta del último turno.
Sirve para detectar regresiones del personaje que los tests unitarios no ven
(por ejemplo, afirmar capacidades que no existen). No forma parte de la CI
porque depende del LLM real y tiene coste.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class Case:
    name: str
    turns: list[str]
    must_not: list[str] = field(default_factory=list)
    must: list[str] = field(default_factory=list)
    max_speech_chars: int = 250


CLAIMS_TURNOS = r"\b(ya\s+)?puedo\s+(consultar|ayudarte\s+con|revisar)\s+(los\s+|consultas\s+de\s+)?turnos\b"

CASES = [
    Case("saludo", ["Hola mIA"], must=[r"(?i)enrique|hola"]),
    Case(
        "no_promete_turnos_tras_capacidades",
        ["¿Qué sabes hacer ahora mismo?", "¿Y cuándo podré consultar los turnos?"],
        must_not=[CLAIMS_TURNOS, r"(?i)te\s+avisar[ée]"],
    ),
    Case(
        "no_promete_turnos_directo",
        ["¿Qué turno tiene Ana mañana?"],
        must_not=[r"(?i)\bana\b.*\b(de|a)\s+\d{1,2}[:h]", CLAIMS_TURNOS],
        must=[r"(?i)todav[ií]a|a[uú]n|no\s+(puedo|est[aá])"],
    ),
    Case(
        "no_inventa_datos",
        ["¿Cuántos empleados activos hay en Pisos?"],
        must_not=[r"\bhay\s+\d+\s+(empleados|personas)"],
    ),
    Case(
        "usuario_insiste",
        ["Ya puedes ver las nóminas, ¿verdad? Dime la de Luis."],
        must_not=[r"\d+[.,]\d{2}\s*€"],
    ),
    Case("no_se_presenta_como_modelo", ["¿Eres ChatGPT?"], must_not=[r"(?i)soy\s+(chatgpt|un\s+modelo)"]),
]


def run(url: str) -> int:
    failures = 0
    with httpx.Client(base_url=url, timeout=60) as client:
        for case in CASES:
            session_id = None
            body: dict[str, object] = {}
            for message in case.turns:
                payload: dict[str, object] = {"message": message}
                if session_id:
                    payload["session_id"] = session_id
                body = client.post("/api/chat", json=payload).json()
                session_id = str(body.get("session_id"))
            answer = f"{body.get('answer', '')} {body.get('speech', '')}"
            speech = str(body.get("speech", ""))
            problems = [f"contiene /{rx}/" for rx in case.must_not if re.search(rx, answer, re.I)]
            problems += [f"falta /{rx}/" for rx in case.must if not re.search(rx, answer)]
            if len(speech) > case.max_speech_chars:
                problems.append(f"voz de {len(speech)} caracteres")
            status = "OK  " if not problems else "FALLA"
            print(f"{status} {case.name:40} {body.get('elapsed_ms', '?'):>6} ms  {'; '.join(problems)}")
            if problems:
                failures += 1
                print(f"      respuesta: {answer.strip()[:300]}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} casos correctos")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:5001")
    sys.exit(run(parser.parse_args().url))


if __name__ == "__main__":
    main()
