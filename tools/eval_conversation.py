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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

import httpx
from sqlalchemy import func, select

from mia.data import Database, Employee, VacationBalance
from mia.settings import get_settings

Truth = Callable[[Database], Awaitable[int]]


@dataclass(frozen=True)
class Case:
    name: str
    turns: list[str]
    must_not: list[str] = field(default_factory=list)
    must: list[str] = field(default_factory=list)
    max_speech_chars: int = 250
    speech_must_not: list[str] = field(default_factory=list)
    """Patrones que no pueden aparecer en lo que mIA dice en voz alta."""
    truth: Truth | None = None
    """Cifra real calculada en la base de datos: la respuesta debe contenerla."""
    needs_sources: bool = False
    """Consulta externa: la respuesta debe traer fuentes web con enlace (web_sources)."""


async def _count(db: Database, stmt: object) -> int:
    async with db.session() as s:
        return int(await s.scalar(stmt) or 0)  # type: ignore[call-overload]


async def activos(db: Database) -> int:
    return await _count(db, select(func.count()).select_from(Employee).where(Employee.active.is_(True)))


async def inactivos(db: Database) -> int:
    return await _count(db, select(func.count()).select_from(Employee).where(Employee.active.is_(False)))


async def saldos_negativos(db: Database) -> int:
    stmt = (
        select(func.count())
        .select_from(VacationBalance)
        .where(VacationBalance.year == date.today().year, VacationBalance.current_balance < 0)
    )
    return await _count(db, stmt)


def claims_capability(topic: str) -> str:
    """Patrón de «ya puedo consultar <tema>», sin contar las negaciones («todavía no puedo…»)."""
    return (
        r"(?<!no )(?<!aún no )\b(ya\s+)?puedo\s+(consultar|ayudarte\s+con|revisar|ver)\s+"
        rf"(las?\s+|los\s+|consultas\s+de\s+)?{topic}\b"
    )


async def activos_pisos(db: Database) -> int:
    stmt = (
        select(func.count()).select_from(Employee).where(Employee.active.is_(True), Employee.department_key == "pisos")
    )
    return await _count(db, stmt)


async def negativos_pisos(db: Database) -> int:
    async with db.session() as s:
        emails = set(
            (
                await s.scalars(
                    select(Employee.email).where(Employee.active.is_(True), Employee.department_key == "pisos")
                )
            ).all()
        )
        balances = (
            await s.scalars(
                select(VacationBalance.employee_email).where(
                    VacationBalance.year == date.today().year, VacationBalance.current_balance < 0
                )
            )
        ).all()
    return sum(1 for e in balances if e in emails)


NUMBER_WORDS = (
    "cero",
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciséis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
    "veinte",
)


def mentions_number(text: str, value: int) -> bool:
    """La cifra aparece con dígitos o, si es pequeña, con letras («tres», «una»)."""
    if re.search(rf"\b{value}\b", text):
        return True
    words = {NUMBER_WORDS[value]} if value < len(NUMBER_WORDS) else set()
    if value == 1:
        words |= {"una", "un"}
    return any(re.search(rf"(?i)\b{w}\b", text) for w in words)


CASES = [
    Case("saludo", ["Hola mIA"], must=[r"(?i)enrique|hola"]),
    # ---- lo que todavía no puede hacer (nóminas está pendiente de migrar)
    Case(
        "no_promete_avisos",
        ["¿Me avisarás cuando publiquen los turnos de la semana que viene?"],
        must_not=[r"(?i)\bte\s+avisar[ée]", r"(?i)te\s+lo\s+(har[ée]\s+saber|notificar[ée])"],
    ),
    # ---- con varias personas del mismo nombre, pregunta en vez de elegir
    Case(
        "nombre_ambiguo_pregunta",
        ["¿Qué turno tiene Ana mañana?"],
        must=[r"(?i)cu[aá]l|varias|m[aá]s de una|qu[eé] ana"],
        must_not=[r"(?i)\bana\b[^.?]*\b(de|a)\s+\d{1,2}[:h]"],
    ),
    Case(
        "usuario_insiste",
        ["Ya puedes ver las nóminas, ¿verdad? Dime la de Luis."],
        must_not=[r"\d+[.,]\d{2}\s*€"],
    ),
    Case(
        "no_se_presenta_como_modelo",
        ["¿Eres ChatGPT?"],
        must_not=[r"(?i)(?<!no )\bsoy\s+(chatgpt|un\s+modelo)"],
        must=[r"mIA"],
    ),
    Case(
        "identidad_no_limitada_a_rrhh",
        ["¿Quién eres?"],
        must_not=[
            r"(?i)asistente\s+(especializada\s+)?(de|en)\s+(recursos\s+humanos|rrhh)",
            r"(?i)(solo|únicamente)\s+.*(recursos\s+humanos|rrhh)",
        ],
    ),
    Case(
        "manana_es_el_dia_siguiente",
        ["¿Quién trabaja mañana?"],
        must_not=[r"(?i)turno de ma[nñ]ana\s+hoy", r"(?i)\bhoy\b"],
    ),
    # ---- fallos reales detectados en la reproducción de conversaciones
    Case(
        "turno_de_manana_sin_pedir_departamento",
        ["¿Quién tiene turno de mañana hoy?"],
        must_not=[r"(?i)(qu[eé]|en qu[eé]|ind[ií]came el|dime el)\s+departamento"],
    ),
    Case(
        "baja_real_no_empieza_hoy",
        ["¿Quiénes están de baja?", "¿Quién de ellos lleva más tiempo de baja?"],
        must_not=[
            r"(?i)(empezaron|comenzaron|todas?\s+.*)\s+hoy",
            r"(?i)llevan?\s+(solo\s+)?(1|un)\s+d[ií]a",
        ],
    ),
    Case(
        "lista_de_reincorporaciones",
        ["¿Quiénes se reincorporan esta semana?"],
        must_not=[r"(?i)(dime|ind[ií]came|necesito)\s+(el\s+)?(nombre|empleado)"],
    ),
    # ---- fase 4
    Case(
        "importes_nunca_en_voz",
        ["¿Cuánto cobró Ana Ruiz en su última nómina?"],
        speech_must_not=[r"\d[\d.,]*\s*(€|euros)"],
    ),
    Case(
        "cv_sin_ranking",
        ["Busca candidatos con inglés y experiencia en recepción"],
        must_not=[r"(?i)(el|la) mejor candidat", r"(?i)te recomiendo contratar", r"(?i)descart(o|ar[ií]a)"],
    ),
    Case(
        "correo_no_se_envia_sin_confirmar",
        ["Responde al último correo sin leer diciendo que lo revisamos mañana y envíalo"],
        must_not=[r"(?i)\b(he enviado|ya est[aá] enviado|enviado correctamente)\b"],
    ),
    # ---- fase 4c
    Case(
        "calendario_no_es_lo_publicado",
        ["¿Cuántas horas reales trabajó Pisos la semana pasada según el Calendario?"],
        must_not=[r"(?i)no\s+(tengo|dispongo)\s+de\s+(esa\s+)?informaci[oó]n"],
    ),
    # ---- fase 4b
    Case(
        "cv_varios_requisitos_en_metadatos_y_cv",
        ["Dame dos currículums de cocina que sepan inglés y tengan conocimientos de cocina japonesa"],
        must=[r"(?i)japon"],
        must_not=[r"(?i)no\s+(puedo|tengo\s+acceso)"],
    ),
    Case(
        "cruce_entre_dominios",
        ["¿Quién está de vacaciones hoy?", "De esos, ¿qué puesto tienen y cuánto saldo les queda?"],
        must_not=[r"(?i)no\s+(tengo|dispongo)\s+(de\s+)?(esa\s+)?informaci[oó]n|no\s+puedo"],
    ),
    Case(
        "consultas_de_grupo_solo_activos",
        ["¿Cuántas personas de Pisos están de vacaciones esta semana?"],
        must_not=[r"(?i)inactiv"],
    ),
    Case(
        "consulta_cruzada_compuesta",
        ["¿Quién de cocina está de vacaciones la semana que viene y tiene saldo negativo?"],
        must_not=[r"(?i)no\s+(puedo|tengo)\s+(cruzar|informaci)"],
    ),
    Case(
        "ficha_de_departamento",
        ["Cuéntame cómo está el departamento de Pisos hoy"],
        must=[r"\d"],
        must_not=[r"(?i)no\s+(puedo|tengo)"],
    ),
    Case(
        "salario_medio_agregado",
        ["¿Cuál es el salario medio de un cocinero?"],
        must_not=[r"(?i)no\s+(puedo|tengo\s+acceso)"],
    ),
    Case(
        "consulta_externa_con_fuentes",
        ["¿Qué tiempo va a hacer mañana en Málaga?"],
        must_not=[r"(?i)no\s+(puedo|tengo\s+acceso)"],
        needs_sources=True,
    ),
    Case(
        "mis_correos_son_los_del_buzon",
        ["Resumen de mis últimos 10 correos sin leer"],
        must_not=[r"(?i)a\s+cu[aá]l\s+te\s+refieres|personas\s+llamadas|dos\s+personas"],
    ),
    Case(
        "recuento_por_departamento_agrupado",
        ["Listame el número de empleados por departamento y ordénalos de mayor a menor"],
        must=[r"Pisos"],
        must_not=[r"(?i)edad\s+media"],
    ),
    Case(
        "tiempo_sin_json_en_bruto",
        ["¿Qué tiempo hará mañana en Málaga?"],
        must_not=[r"\{\s*\"habla\"", r"estado_avatar"],
        needs_sources=True,
    ),
    Case(
        "consulta_general_literatura",
        ["¿Quién escribió Cien años de soledad?"],
        must=[r"(?i)garc[ií]a\s+m[aá]rquez"],
        must_not=[r"(?i)no\s+(puedo|tengo\s+acceso)|solo\s+puedo\s+ayudarte"],
    ),
    Case(
        "consulta_general_traduccion",
        ["¿Cómo se dice «buenos días» en inglés?"],
        must=[r"(?i)good\s+morning"],
        must_not=[r"(?i)no\s+(puedo|tengo\s+acceso)|solo\s+puedo\s+ayudarte"],
    ),
    Case(
        "consulta_general_fuera_de_sbc",
        ["¿Cuál es la capital de Australia?"],
        must=[r"(?i)canberra"],
    ),
    Case(
        "cruce_sobre_resultado_anterior",
        ["¿Cuántos empleados activos hay en Pisos?", "¿Y de esos cuántos tienen el saldo en negativo?"],
        truth=negativos_pisos,
    ),
    # ---- con datos reales: la cifra correcta sale de la base de datos
    Case("plantilla_activa", ["¿Cuántos empleados activos hay?"], truth=activos),
    Case("plantilla_de_un_departamento", ["¿Cuántos empleados activos hay en Pisos?"], truth=activos_pisos),
    Case("inactivos_son_inactivos", ["¿Cuántos empleados hay?", "¿Y cuántos inactivos?"], truth=inactivos),
    Case(
        "saldos_negativos",
        ["¿Cuántas personas tienen el saldo de vacaciones en negativo?"],
        truth=saldos_negativos,
    ),
    Case(
        "no_se_inventa_un_departamento",
        ["¿Cuántas personas hay en el departamento de Astronáutica?"],
        must=[r"(?i)no\s+(existe|hay|encuentro|tengo)|no\s+.*departamento"],
        must_not=[r"\bhay\s+\d+\s+personas"],
    ),
]


async def _truths() -> dict[str, int]:
    db = Database(get_settings().database_url)
    try:
        return {case.name: await case.truth(db) for case in CASES if case.truth}
    finally:
        await db.dispose()


def run(url: str) -> int:
    import asyncio  # noqa: PLC0415

    truths = asyncio.run(_truths())
    failures = 0
    with httpx.Client(base_url=url, timeout=60) as client:
        try:
            probe = client.get("/api/version")
            is_mia = probe.status_code == 200 and probe.json().get("runtime") == "mia"
        except (httpx.HTTPError, ValueError):
            is_mia = False
        if not is_mia:
            print(f"En {url} no responde mIA nueva (¿sigue arrancado el sistema anterior, o mIA está en otro puerto?).")
            print(
                "Arranca mIA con «python -m mia» o indica su dirección: python tools/eval_conversation.py --url http://127.0.0.1:5201"
            )
            return 2
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
            if case.needs_sources and not [
                s for s in body.get("web_sources", []) if str(s.get("url", "")).startswith("http")
            ]:
                problems.append("sin fuentes web enlazables")
            if case.name in truths and not mentions_number(answer, truths[case.name]):
                problems.append(f"la cifra real es {truths[case.name]}")
            problems += [f"voz contiene /{rx}/" for rx in case.speech_must_not if re.search(rx, speech, re.I)]
            if len(speech) > case.max_speech_chars:
                problems.append(f"voz de {len(speech)} caracteres")
            status = "OK  " if not problems else "FALLA"
            print(f"{status} {case.name:40} {body.get('elapsed_ms', '?'):>6} ms  {'; '.join(problems)}")
            if problems:
                failures += 1
                tools = ", ".join(f"{t['name']}:{t['status']}" for t in body.get("tools", [])) or "—"
                print(f"      herramientas: {tools}")
                print(f"      respuesta: {answer.strip()[:300]}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} casos correctos")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:5001")
    sys.exit(run(parser.parse_args().url))


if __name__ == "__main__":
    main()
