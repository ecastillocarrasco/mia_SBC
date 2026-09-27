"""Fase 4: herramientas de selección, nóminas, documentos, trabajo temporal, informes y correo."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.conversation.tools import LAST_TABLE
from mia.data import (
    Candidate,
    CvChunk,
    CvText,
    Database,
    Employee,
    Payslip,
    SignedDocument,
    TtTimesheet,
)
from mia.domains import build_registry
from mia.domains.curriculums.indexer import pack
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider
from mia.settings import Environment, Settings
from mia.sources.graph import GraphClient
from mia.sources.sharepoint import StaticTokenProvider
from mia.text import normalize_key
from tests.dbutil import fresh_database

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
ADMIN = UserContext("u1", "Enrique", roles=frozenset({"mia.admin"}))


def _emp(sp_id: int, name: str, key: str, dept: str = "Pisos") -> Employee:
    return Employee(
        sp_id=sp_id,
        name=name,
        name_key=normalize_key(name),
        active=True,
        department=dept,
        department_key=normalize_key(dept),
        email=f"{key}@sbc.test",
        person_key=key,
    )


async def _seed(db: Database, llm: FakeLLMProvider) -> None:
    cvs = {
        8316: ("Lucía Martín", "Recepcionista con alemán fluido y experiencia en hoteles de cinco estrellas"),
        8317: ("Pablo Ruiz", "Cocinero de partida, cocina mediterránea y pastelería"),
    }
    rows: list[Any] = [_emp(1, "Ana Ruiz", "pk-ana"), _emp(2, "Eva Sol", "pk-eva")]
    for cid, (name, text) in cvs.items():
        rows.append(
            Candidate(
                sp_id=cid,
                name=name,
                name_key=normalize_key(name),
                department="Recepción",
                department_key="recepcion",
                status="Nuevo",
            )
        )
        rows.append(CvText(document_id=cid, candidate_id=cid, status="ok", text=text))
        vector = (await llm.embed([text], "x"))[0]
        rows.append(CvChunk(document_id=cid, candidate_id=cid, position=0, text=text, embedding=pack(vector)))
    for month in (1, 2, 3, 5, 6, 7, 8):
        rows.append(
            Payslip(
                sp_id=100 + month,
                person_key="pk-ana",
                employee_email="pk-ana@sbc.test",
                year=2026,
                month=month,
                period=f"2026-{month:02d}",
                read=month != 8,
                special=False,
            )
        )
    rows.append(Payslip(sp_id=200, person_key="pk-ana", year=2026, month=7, period="2026-07", special=True))
    rows.append(
        SignedDocument(sp_id=1, person_key="pk-ana", doc_type="Protección de datos", file_name="LOPD.pdf")
    )
    rows += [
        TtTimesheet(
            sp_id=1,
            day=date(2026, 9, 2),
            worker_name="Leo T",
            company="ETT Uno",
            department="Cocina",
            department_key="cocina",
            hours_total=8,
            hours_night=0,
            amount=120.0,
            status="Validado",
        ),
        TtTimesheet(
            sp_id=2,
            day=date(2026, 9, 3),
            worker_name="Leo T",
            company="ETT Uno",
            department="Cocina",
            department_key="cocina",
            hours_total=6.5,
            hours_night=2,
            amount=110.5,
            status="Validado",
        ),
    ]
    async with db.session() as s:
        s.add_all(rows)


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[tuple[ToolRegistry, Database, Settings]]:
    db = await fresh_database(tmp_path, "p4d.db")
    llm = FakeLLMProvider()
    await _seed(db, llm)
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        reports={"directory": tmp_path / "rep"},  # type: ignore[call-arg]
        mail={"mailbox": "rrhh@sbc.test", "send_enabled": True},
    )
    yield build_registry(db, settings=settings, llm=llm), db, settings
    await db.dispose()


async def call(
    registry: ToolRegistry,
    name: str,
    state: dict[str, Any] | None = None,
    *,
    message: str = "",
    request_id: str = "r1",
    **args: Any,
) -> Any:
    ctx = ToolContext(
        user=ADMIN,
        request_id=request_id,
        now=NOW,
        session_state=state if state is not None else {},
        user_message=message,
    )
    execution = await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)
    return execution.result


async def test_cv_search_returns_evidence_not_a_ranking(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "buscar_candidatos", consulta="recepcionista con alemán fluido")
    assert result.status is ToolStatus.OK
    first = result.summary["coincidencias"][0]
    assert first["nombre"] == "Lucía Martín" and "alemán" in first["evidencia"]
    assert "SEL-001" in result.summary["regla"]


async def test_payslips_list_missing_months_and_never_amounts(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "nominas_persona", empleado_id=1)
    assert result.summary["meses_sin_nomina_hasta_el_mes_pasado"] == [4]
    assert result.summary["no_leidas"] == 1
    assert any(n["paga_especial"] for n in result.summary["nominas"])
    assert "importe" not in json.dumps(result.summary).lower().replace("importes", "")


async def test_who_lacks_the_payslip_of_a_month(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "nominas_periodo", periodo="2026-08")
    assert result.summary["personas_sin_nomina"] == ["Eva Sol"]


async def test_missing_signed_documents(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "documentos_faltantes", tipo="protección de datos")
    assert result.summary["personas"] == ["Eva Sol"]
    docs = await call(registry, "documentos_persona", empleado_id=1)
    assert docs.summary["por_tipo"] == {"Protección de datos": 1}


async def test_temporary_work_totals(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "boletines_tt", desde="2026-09-01", hasta="2026-09-30")
    assert (result.summary["horas_totales"], result.summary["importe_total"]) == (14.5, 230.5)
    assert result.summary["desglose"]["empresa: ETT Uno"]["boletines"] == 2


@pytest.mark.parametrize("fmt", ["pdf", "xlsx"])
async def test_report_from_last_table(env: Any, fmt: str) -> None:
    registry, _, _ = env
    state: dict[str, Any] = {}
    missing = await call(registry, "generar_informe", state, formato=fmt)
    assert missing.status is ToolStatus.NOT_FOUND
    state[LAST_TABLE] = {
        "title": "Plantilla Pisos",
        "columns": ["Nombre", "Puesto"],
        "rows": [["Ana Ruiz", "Camarera"], ["Eva Sol", "Gobernanta"]],
    }
    result = await call(registry, "generar_informe", state, formato=fmt)
    assert result.status is ToolStatus.OK
    assert result.presentation["url"].startswith("/api/reports/")
    path = next((Path(env[2].reports.directory)).glob(f"*.{fmt}"))
    assert path.read_bytes()[:4] in (b"%PDF", b"PK\x03\x04")


# ------------------------------------------------------------------ correo (COR-001)
class _FakeGraph:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/mailFolders/inbox/messages"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "AAMk-1",
                            "subject": "Solicitud",
                            "isRead": False,
                            "from": {"emailAddress": {"name": "Ana", "address": "a@x"}},
                            "bodyPreview": "Hola",
                        }
                    ]
                },
            )
        if path.endswith("/createReply"):
            return httpx.Response(201, json={"id": "DRAFT-1"})
        if path.endswith("/send"):
            self.sent.append(path)
            return httpx.Response(202)
        if "/messages/AAMk-1" in path:
            return httpx.Response(
                200,
                json={
                    "subject": "Solicitud",
                    "body": {"contentType": "html", "content": "<p>Hola &amp; gracias</p>"},
                },
            )
        return httpx.Response(404)


async def test_mail_send_requires_a_previous_draft_and_explicit_confirmation(env: Any) -> None:
    _, db, settings = env
    fake = _FakeGraph()
    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(fake.handler))
    registry = build_registry(db, settings=settings, graph=graph)
    state: dict[str, Any] = {}
    inbox = await call(registry, "correos_sin_leer", state)
    assert inbox.summary["correos"][0]["ref"] == "c1"
    read = await call(registry, "leer_correo", state, ref="c1")
    assert read.summary["texto"] == "Hola & gracias"
    draft = await call(
        registry, "preparar_respuesta", state, ref="c1", texto="Recibido, gracias.", request_id="t1"
    )
    assert draft.summary["borrador"] == "b1"
    same_turn = await call(
        registry, "enviar_borrador", state, borrador="b1", message="envíalo", request_id="t1"
    )
    assert same_turn.status is ToolStatus.PERMISSION_DENIED
    no_confirmation = await call(
        registry, "enviar_borrador", state, borrador="b1", message="¿qué pone?", request_id="t2"
    )
    assert no_confirmation.status is ToolStatus.PERMISSION_DENIED
    hesitant = await call(
        registry, "enviar_borrador", state, borrador="b1", message="no, espera", request_id="t3"
    )
    assert hesitant.status is ToolStatus.PERMISSION_DENIED
    assert fake.sent == []
    ok = await call(registry, "enviar_borrador", state, borrador="b1", message="Sí, envíalo", request_id="t4")
    assert ok.status is ToolStatus.OK and len(fake.sent) == 1
    await graph.aclose()


async def test_disabled_domain_is_not_offered(env: Any) -> None:
    _, db, settings = env
    registry = build_registry(db, settings=settings, enabled=["empleados"])
    names = {t.name for t in registry.schemas_for(ADMIN)}
    assert "nominas_persona" not in names and "buscar_empleado" in names
    assert "nóminas" in registry.capabilities_for(ADMIN)
