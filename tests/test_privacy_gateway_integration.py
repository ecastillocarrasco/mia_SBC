"""Etapa 4: integración real, no solo del gateway aislado.

Recorrido completo: Usuario → ConversationEngine → herramienta real (buscar_empleado, contra una BD
real sembrada con datos sintéticos) → resultado de la herramienta (JSON con nombre real) → Privacy
Gateway → "proveedor" (FakeLLMProvider, pero por el MISMO camino que seguiría uno real) →
restauración → respuesta final al usuario.

No se verifica el gateway en aislado (eso ya está en tests/test_privacy_gateway.py): aquí se
comprueba que el nombre real de una persona, que viene de un resultado de herramienta (no del mensaje
del usuario), nunca llega en texto plano a `fake.requests` — y que sí aparece, restaurado, en la
respuesta final que ve el usuario.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx

from mia.auth import UserContext
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.conversation import ConversationEngine
from mia.conversation.events import ResultEvent
from mia.conversation.tools import ToolRegistry
from mia.data import Database, Employee, Payslip
from mia.llm.base import LLMRequest
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.modules.registry import build_registry
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.settings import PrivacyGatewaySettings
from tests.dbutil import fresh_database
from tests.hr_seed import seed
from tests.test_phase4b import _pdf

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))

Script = Callable[[LLMRequest], list[object]]


def _echo_tool_result_script(first_call_name: str, first_call_args: dict[str, object]) -> Script:
    """Guion de 2 rondas reutilizable: ronda 1 llama a una herramienta real; ronda 2 "cita" literalmente
    el resultado — así, si el gateway no protegiera nada, el dato real reaparecería en la respuesta."""

    def _script(request: LLMRequest) -> list[object]:
        last = request.messages[-1]
        if last.role == "tool":
            return final_answer(texto=last.content, habla="Resultado de la consulta.", estado_avatar="sonriendo")
        return tool_call(first_call_name, first_call_args)

    return _script


async def _seeded_db(tmp_path: Path, name: str) -> Database:
    db = await fresh_database(tmp_path, name)
    await seed(db)
    return db


async def _run_turn(
    db: Database, registry: ToolRegistry, script: Script, *, message: str, enabled: bool, policy: str = "standard"
) -> tuple[object, FakeLLMProvider]:
    fake = FakeLLMProvider(script=script)
    settings = (
        PrivacyGatewaySettings(
            enabled=True, vault_key="clave-de-prueba-no-real", vault_ttl_seconds=60, default_policy=policy
        )
        if enabled
        else PrivacyGatewaySettings(enabled=False)
    )
    gateway = PrivacyGateway(fake, settings, provider_name="test", model="test-model")
    engine = ConversationEngine(llm=gateway, tools=registry, db=db, max_tool_rounds=4)

    result = None
    async for event in engine.run(message=message, user=ADMIN, session_id=None):
        if isinstance(event, ResultEvent):
            result = event.result
    assert result is not None
    return result, fake


def _all_outgoing_text(fake: FakeLLMProvider) -> str:
    return json.dumps(
        [m.content for req in fake.requests for m in req.messages],
        ensure_ascii=False,
    )


_script = _echo_tool_result_script("buscar_empleado", {"nombre": "Eva Sol"})


async def test_empleados_real_tool_result_pii_never_reaches_the_simulated_provider(tmp_path: Path) -> None:
    db = await _seeded_db(tmp_path, "privacy_empleados.db")
    registry = build_registry(db)

    result, fake = await _run_turn(
        db, registry, _script, message="¿En qué departamento trabaja Eva Sol?", enabled=True
    )

    assert result.status == "ok"
    assert len(fake.requests) == 2  # ronda de herramienta + ronda de respuesta final
    outgoing = _all_outgoing_text(fake)
    assert "Eva Sol" not in outgoing
    assert "[PERSON_" in outgoing  # el pseudo-token sí viaja

    assert "Eva Sol" in result.answer  # restaurado en la misma operación/usuario
    assert "[PERSON_" not in result.answer


async def test_gateway_disabled_still_lets_the_same_flow_work_unprotected(tmp_path: Path) -> None:
    """Control: con enabled=False, el mismo recorrido funciona igual (paso directo), confirmando que
    activar la protección no es lo que hace que la función exista — solo decide si se protege."""
    db = await _seeded_db(tmp_path, "privacy_empleados_off.db")
    registry = build_registry(db)

    result, fake = await _run_turn(
        db, registry, _script, message="¿En qué departamento trabaja Eva Sol?", enabled=False
    )

    assert "Eva Sol" in result.answer
    assert "Eva Sol" in _all_outgoing_text(fake)  # sin protección, viaja también en claro


async def test_turnos_domain_employee_name_from_shift_data_is_protected(tmp_path: Path) -> None:
    """Dominio Turnos: el nombre no viene del mensaje del usuario, viene de ShiftDay en BD."""
    db = await _seeded_db(tmp_path, "privacy_turnos.db")
    registry = build_registry(db)
    script = _echo_tool_result_script("turnos_dia", {"fecha": "2026-08-05"})

    result, fake = await _run_turn(db, registry, script, message="¿Quién trabaja hoy?", enabled=True)

    assert result.status == "ok"
    outgoing = _all_outgoing_text(fake)
    assert "Ana Gómez" not in outgoing  # trabaja en Cocina el 2026-08-05 según la siembra
    assert "[PERSON_" in outgoing
    assert "Ana Gómez" in result.answer


async def test_vacaciones_domain_balance_names_are_protected(tmp_path: Path) -> None:
    """Dominio Vacaciones: nombres y saldo vienen de VacationBalance, no del mensaje del usuario."""
    db = await _seeded_db(tmp_path, "privacy_vacaciones.db")
    registry = build_registry(db)
    script = _echo_tool_result_script("saldo_vacaciones", {})

    result, fake = await _run_turn(db, registry, script, message="¿Cuál es el saldo de vacaciones?", enabled=True)

    assert result.status == "ok"
    outgoing = _all_outgoing_text(fake)
    assert "Ana Ruiz Sanz" not in outgoing
    assert "Ana Gómez" not in outgoing
    assert "[PERSON_" in outgoing
    assert "Ana Ruiz Sanz" in result.answer and "Ana Gómez" in result.answer


async def test_nominas_domain_individual_names_and_amounts_are_protected(tmp_path: Path) -> None:
    """Dominio Nóminas: el más sensible de todos (NOM-004/005; Escenario B de la sección 30: «informe
    salarial comparativo de varios empleados»). ``ranking_salarial`` es, a propósito, la herramienta que
    SÍ devuelve nombre e importe individuales (sobre un grupo ≥3, por diseño de negocio) — exactamente
    el tipo de contenido que el Privacy Gateway debe tokenizar antes de que salga hacia el proveedor."""
    # Nombres reales, no "Cocinero Pérez" (mezclar el puesto dentro del campo nombre confunde al NER:
    # verificado que con nombres propios normales los tres se detectan sin problema).
    names_and_nets = [("Marta Ruiz", "pk-201", 1700.0), ("Carlos López", "pk-202", 1600.0), ("Sofía Pérez", "pk-203", 1500.0)]
    db = await fresh_database(tmp_path, "privacy_nominas.db")
    async with db.session() as s:
        for n, (name, pk, _net) in enumerate(names_and_nets, start=201):
            s.add(
                Employee(
                    sp_id=n, name=name, name_key=name.lower(), active=True, department="Cocina",
                    department_key="cocina", position="Cocinero", person_key=pk,
                )
            )
            s.add(Payslip(sp_id=n, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_spid = {201 + i: net for i, (_, _, net) in enumerate(names_and_nets)}

    def files(request: httpx.Request) -> httpx.Response:
        match = re.search(r"items\((\d+)\)/File", request.url.path)
        net = net_by_spid[int(match.group(1))] if match else 0.0
        gross = net + 330.15
        fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        text = (
            "EMPRESA SUNSET BEACH CLUB\nMensual - Agosto 2026\n"
            "REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR\n"
            f"{fmt(gross - 266.67)} 266,67 {fmt(gross)} {fmt(gross)} {fmt(gross)} {fmt(gross)} 330,15\n"
            f"Tributación I.R.P.F. (11,50 %) 214,67\n{fmt(net)} Líquido a percibir\n"
        )
        return httpx.Response(200, content=_pdf(text))

    sp = SharePointClient(site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files))
    registry = build_registry(db, sharepoint=sp)
    script = _echo_tool_result_script("ranking_salarial", {"departamento": "Cocina", "cuantos": 3})

    result, fake = await _run_turn(
        db, registry, script, message="¿Quién cobra más en Cocina?", enabled=True
    )
    await sp.aclose()

    assert result.status == "ok"
    outgoing = _all_outgoing_text(fake)
    # El nombre, que es lo que permite ATRIBUIR el importe a una persona concreta, no debe viajar en
    # claro. El importe en sí (1700.0) sí puede seguir viajando desacoplado del nombre real: una vez
    # sustituido por [PERSON_NNN], nadie fuera del backend puede unir esa cifra con "Marta Ruiz" — es
    # el límite real de esta implementación (pseudonimización del identificador, no cifrado
    # homomórfico de la cifra), documentado como tal en PRIVACY_GATEWAY_PROGRESS.md.
    assert "Marta Ruiz" not in outgoing
    assert "Carlos López" not in outgoing
    assert "Sofía Pérez" not in outgoing
    assert "[PERSON_" in outgoing

    assert "Marta Ruiz" in result.answer
    assert "1700" in result.answer or "1.700" in result.answer


async def test_nominas_domain_individual_amounts_redacted_under_strict_policy(tmp_path: Path) -> None:
    """Ajuste 1 de la aprobación condicionada del Bloque I: bajo STRICT/AGGREGATED, el importe
    INDIVIDUAL (ya desligado del nombre real por el pseudo-token) tampoco debe viajar en claro hacia
    el proveedor cuando queda ligado, en el mismo registro, a una persona ya identificada. Reutiliza
    exactamente la misma siembra que la prueba anterior (política por defecto) para demostrar que es
    la MISMA funcionalidad, solo con el importe también protegido bajo una política más estricta — no
    una anonimización indiscriminada nueva y distinta."""
    names_and_nets = [("Marta Ruiz", "pk-301", 1700.0), ("Carlos López", "pk-302", 1600.0), ("Sofía Pérez", "pk-303", 1500.0)]
    db = await fresh_database(tmp_path, "privacy_nominas_strict.db")
    async with db.session() as s:
        for n, (name, pk, _net) in enumerate(names_and_nets, start=301):
            s.add(
                Employee(
                    sp_id=n, name=name, name_key=name.lower(), active=True, department="Cocina",
                    department_key="cocina", position="Cocinero", person_key=pk,
                )
            )
            s.add(Payslip(sp_id=n, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_spid = {301 + i: net for i, (_, _, net) in enumerate(names_and_nets)}

    def files(request: httpx.Request) -> httpx.Response:
        match = re.search(r"items\((\d+)\)/File", request.url.path)
        net = net_by_spid[int(match.group(1))] if match else 0.0
        gross = net + 330.15
        fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        text = (
            "EMPRESA SUNSET BEACH CLUB\nMensual - Agosto 2026\n"
            "REM. TOTAL P.P. EXTRAS BASE C.C. BASE A.T. Y DES BASE I.R.P.F. T. DEVENGADO T. A DEDUCIR\n"
            f"{fmt(gross - 266.67)} 266,67 {fmt(gross)} {fmt(gross)} {fmt(gross)} {fmt(gross)} 330,15\n"
            f"Tributación I.R.P.F. (11,50 %) 214,67\n{fmt(net)} Líquido a percibir\n"
        )
        return httpx.Response(200, content=_pdf(text))

    sp = SharePointClient(site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files))
    registry = build_registry(db, sharepoint=sp)
    script = _echo_tool_result_script("ranking_salarial", {"departamento": "Cocina", "cuantos": 3})

    result, fake = await _run_turn(
        db, registry, script, message="¿Quién cobra más en Cocina?", enabled=True, policy="strict"
    )
    await sp.aclose()

    assert result.status == "ok"
    outgoing = _all_outgoing_text(fake)
    assert "Marta Ruiz" not in outgoing
    assert "Carlos López" not in outgoing
    assert "Sofía Pérez" not in outgoing
    assert "[PERSON_" in outgoing
    # El ajuste del punto 1: a diferencia de la política por defecto, bajo STRICT el importe
    # individual tampoco viaja en claro una vez ligado a una persona ya identificada.
    assert "1700" not in outgoing and "1.700" not in outgoing
    assert "1600" not in outgoing and "1.600" not in outgoing
    assert "1500" not in outgoing and "1.500" not in outgoing
    assert "IMPORTE_INDIVIDUAL_PROTEGIDO" in outgoing

    # El nombre sí se restaura (es un pseudo-token reversible, ligado a esta operación): el marcador de
    # importe NO es un token del vault, es deliberadamente irreversible — bajo STRICT, el LLM nunca
    # conoció la cifra real, así que no puede devolverla en la respuesta conversacional. Esto es
    # intencional: el dato real para un DOCUMENTO final (informe) lo debe generar el backend
    # directamente a partir de los datos originales, sin depender de que el LLM lo repita (ver
    # docstring de economic_minimization.py) — algo que una respuesta de chat simulada por eco no
    # ejercita, pero que el motor de informes (Bloque II) deberá demostrar con sus propias pruebas.
    assert "Marta Ruiz" in result.answer
    assert "1700" not in result.answer and "1.700" not in result.answer
    assert "IMPORTE_INDIVIDUAL_PROTEGIDO" in result.answer
