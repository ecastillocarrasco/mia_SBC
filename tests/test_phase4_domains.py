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
from mia.connectors.graph import GraphClient
from mia.connectors.sharepoint import StaticTokenProvider
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
from mia.llm import ToolCall
from mia.llm.fake import FakeLLMProvider
from mia.modules.rrhh import build_registry
from mia.modules.rrhh.curriculums.indexer import normalize
from mia.settings import Environment, Settings
from mia.text import normalize_key
from tests.dbutil import POSTGRES_URL, fresh_database

requires_postgres = pytest.mark.skipif(
    not POSTGRES_URL, reason="pgvector (cosine_distance / DISTINCT ON) solo funciona contra Postgres real"
)

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
        rows.append(CvChunk(document_id=cid, candidate_id=cid, position=0, text=text, embedding=normalize(vector)))
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
    rows.append(SignedDocument(sp_id=1, person_key="pk-ana", doc_type="Protección de datos", file_name="LOPD.pdf"))
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


@requires_postgres
async def test_cv_search_returns_evidence_not_a_ranking(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "candidatos_parecidos", consulta="recepcionista con alemán fluido")
    assert result.status is ToolStatus.OK
    first = result.summary["coincidencias"][0]
    assert first["nombre"] == "Lucía Martín" and "alemán" in first["evidencia"]
    assert "SEL-001" in result.summary["regla"]


async def test_payslips_list_missing_months_and_never_amounts(env: Any) -> None:
    registry, _, _ = env
    result = await call(registry, "nominas_persona", empleado_id=1)
    assert result.summary["meses_sin_nomina_2026_hasta_el_mes_pasado"] == [4]
    assert result.summary["por_tipo"] == {"nómina mensual": 7, "paga extra": 1}
    assert result.summary["mas_reciente"] == "2026-08"
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


@pytest.mark.parametrize("fmt", ["pdf", "xlsx", "pptx"])
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
    def __init__(self, recipient: str = "ana@x.test") -> None:
        self.sent: list[str] = []
        self.recipient = recipient
        self.patched: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
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
        if path.endswith("/messages/DRAFT-1") and request.method == "PATCH":
            self.patched.append(path)
            return httpx.Response(200, json={})
        if path.endswith("/messages/DRAFT-1") and request.method == "DELETE":
            return httpx.Response(204)
        if path.endswith("/messages/DRAFT-1"):
            return httpx.Response(200, json={"toRecipients": [{"emailAddress": {"address": self.recipient}}]})
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
    draft = await call(registry, "preparar_respuesta", state, ref="c1", texto="Recibido, gracias.", request_id="t1")
    assert draft.summary["borrador"] == "b1"
    same_turn = await call(registry, "enviar_borrador", state, borrador="b1", message="envíalo", request_id="t1")
    assert same_turn.status is ToolStatus.PERMISSION_DENIED
    no_confirmation = await call(
        registry, "enviar_borrador", state, borrador="b1", message="¿qué pone?", request_id="t2"
    )
    assert no_confirmation.status is ToolStatus.PERMISSION_DENIED
    hesitant = await call(registry, "enviar_borrador", state, borrador="b1", message="no, espera", request_id="t3")
    assert hesitant.status is ToolStatus.PERMISSION_DENIED
    assert fake.sent == []
    ok = await call(registry, "enviar_borrador", state, borrador="b1", message="Sí, envíalo", request_id="t4")
    assert ok.status is ToolStatus.OK and len(fake.sent) == 1
    await graph.aclose()


async def test_leer_correo_reads_attachment_text(env: Any) -> None:
    """``leer_correo`` debe devolver tambien el texto de los adjuntos legibles, no solo su nombre."""
    import base64

    _, db, settings = env

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/mailFolders/inbox/messages"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "AAMk-2",
                            "subject": "Contrato",
                            "isRead": False,
                            "from": {"emailAddress": {"name": "Ana", "address": "a@x"}},
                            "bodyPreview": "Adjunto el documento",
                        }
                    ]
                },
            )
        content = base64.b64encode(b"Clausula de confidencialidad del contrato.").decode()
        if path.endswith("/messages/AAMk-2/attachments"):
            # Listado SIN contentBytes: Graph rechaza ese campo en el $select de la colección
            # (solo existe en el tipo derivado fileAttachment, no en el tipo base attachment).
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "att-1",
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "name": "contrato.txt",
                            "size": 42,
                            "contentType": "text/plain",
                        }
                    ]
                },
            )
        if path.endswith("/messages/AAMk-2/attachments/att-1"):
            return httpx.Response(
                200,
                json={
                    "id": "att-1",
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "contrato.txt",
                    "size": 42,
                    "contentType": "text/plain",
                    "contentBytes": content,
                },
            )
        if "/messages/AAMk-2" in path:
            return httpx.Response(
                200,
                json={
                    "subject": "Contrato",
                    "body": {"contentType": "text", "content": "Adjunto el documento"},
                    "hasAttachments": True,
                },
            )
        return httpx.Response(404)

    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(handler))
    registry = build_registry(db, settings=settings, graph=graph)
    state: dict[str, Any] = {}
    await call(registry, "correos_sin_leer", state)
    read = await call(registry, "leer_correo", state, ref="c1")
    await graph.aclose()
    assert read.summary["adjuntos"] == [
        {
            "nombre": "contrato.txt",
            "contenido": "Clausula de confidencialidad del contrato.",
            "url": "/api/mail/attachment/AAMk-2/att-1",
        }
    ]


async def test_disabled_domain_is_not_offered(env: Any) -> None:
    _, db, settings = env
    registry = build_registry(db, settings=settings, enabled=["empleados"])
    names = {t.name for t in registry.schemas_for(ADMIN)}
    assert "nominas_persona" not in names and "buscar_empleado" in names
    assert "nóminas" in registry.capabilities_for(ADMIN)


async def _mail_env(env: Any, recipient: str) -> tuple[ToolRegistry, dict[str, Any], _FakeGraph, GraphClient]:
    _, db, settings = env
    fake = _FakeGraph(recipient)
    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(fake.handler))
    registry = build_registry(db, settings=settings, graph=graph)
    state: dict[str, Any] = {}
    await call(registry, "correos_sin_leer", state)
    await call(registry, "preparar_respuesta", state, ref="c1", texto="Recibido.", request_id="t1")
    return registry, state, fake, graph


async def test_mail_to_noreply_is_never_sent(env: Any) -> None:
    registry, state, fake, graph = await _mail_env(env, "no-reply@empresa.test")
    result = await call(registry, "enviar_borrador", state, borrador="b1", message="sí, envíalo", request_id="t2")
    await graph.aclose()
    assert result.status is ToolStatus.PERMISSION_DENIED and fake.sent == []


async def test_editing_a_draft_requires_confirming_again(env: Any) -> None:
    registry, state, fake, graph = await _mail_env(env, "ana@x.test")
    await call(registry, "modificar_borrador", state, borrador="b1", texto="Recibido, gracias.", request_id="t2")
    same_turn = await call(registry, "enviar_borrador", state, borrador="b1", message="envíalo", request_id="t2")
    assert same_turn.status is ToolStatus.PERMISSION_DENIED and fake.patched
    ok = await call(registry, "enviar_borrador", state, borrador="b1", message="sí", request_id="t3")
    again = await call(registry, "enviar_borrador", state, borrador="b1", message="sí", request_id="t4")
    await graph.aclose()
    assert ok.status is ToolStatus.OK and again.status is ToolStatus.PERMISSION_DENIED and len(fake.sent) == 1


async def test_discarded_draft_cannot_be_sent(env: Any) -> None:
    registry, state, fake, graph = await _mail_env(env, "ana@x.test")
    assert (await call(registry, "descartar_borrador", state, borrador="b1")).status is ToolStatus.OK
    result = await call(registry, "enviar_borrador", state, borrador="b1", message="sí", request_id="t2")
    await graph.aclose()
    assert result.status is ToolStatus.NOT_FOUND and fake.sent == []


@requires_postgres
async def test_filter_candidates_with_and_or_not_and_unique_people(env: Any) -> None:
    registry, db, _ = env
    async with db.session() as s:
        s.add_all(
            [
                Candidate(
                    sp_id=8318,
                    name="Lucía Martín",
                    name_key="lucia martin",
                    department="Recepción",
                    department_key="recepcion",
                    status="Nuevo",
                ),  # segunda candidatura de la misma persona
                CvText(
                    document_id=8318, candidate_id=8318, status="ok", text="Recepcionista con alemán, antes en Marriott"
                ),
            ]
        )
    both = await call(registry, "buscar_candidatos", requisitos=[{"termino": "marriott", "equivalentes": ["hoteles"]}])
    assert both.summary["cumplen_todos"] == 2 and both.summary["personas_unicas"] == 1


@requires_postgres
async def test_requirements_check_metadata_first_then_the_cv(env: Any) -> None:
    """Caso real: «cocina, inglés y cocina japonesa» solo encontraba el inglés y no miraba los CV."""
    registry, db, _ = env
    async with db.session() as s:
        s.add_all(
            [
                Candidate(
                    sp_id=9001,
                    name="Kenji Sato",
                    name_key="kenji sato",
                    department="Cocina",
                    department_key="cocina",
                    status="Nuevo",
                    languages="Inglés C1",
                    extra={"Especialidad": "Sushi y cocina nikkei"},
                ),
                CvText(document_id=9001, candidate_id=9001, status="ok", text="Cocinero en restaurante japonés"),
                Candidate(
                    sp_id=9002,
                    name="Marta Gil",
                    name_key="marta gil",
                    department="Cocina",
                    department_key="cocina",
                    status="Nuevo",
                ),
                CvText(
                    document_id=9002,
                    candidate_id=9002,
                    status="ok",
                    text="Chef de partida. Speaks fluent English. Formación en washoku en Kioto.",
                ),
                Candidate(
                    sp_id=9003,
                    name="Luis Paz",
                    name_key="luis paz",
                    department="Cocina",
                    department_key="cocina",
                    status="Nuevo",
                    languages="Inglés B2",
                ),
                CvText(document_id=9003, candidate_id=9003, status="ok", text="Cocina mediterránea y arroces"),
            ]
        )
    result = await call(
        registry,
        "buscar_candidatos",
        departamento="Cocina",
        mostrar=2,
        requisitos=[
            {"termino": "inglés"},
            {"termino": "cocina japonesa", "equivalentes": ["japonés", "japanese", "sushi", "washoku"]},
        ],
    )
    s = result.summary
    assert s["cumplen_todos"] == 2  # Luis tiene inglés pero no cocina japonesa: no cumple
    first, second = s["muestra"]
    assert first["nombre"] == "Kenji Sato"  # todo en metadatos: primero
    assert first["requisitos"]["inglés"]["donde"] == "metadatos"
    assert first["requisitos"]["cocina japonesa"] == {
        "donde": "metadatos",
        "evidencia": "Especialidad: Sushi y cocina nikkei",
    }
    assert second["nombre"] == "Marta Gil" and second["requisitos"]["cocina japonesa"]["donde"] == "cv"
    assert "washoku" in second["requisitos"]["cocina japonesa"]["evidencia"]
    assert s["donde_se_cumple_cada_requisito"]["inglés"] == {"metadatos": 2, "cv": 1}


async def test_candidate_with_several_applications_is_not_ambiguous(env: Any) -> None:
    """Fallo real: «resúmeme el CV de Gisella Terzolo» respondía que no había resultados."""
    registry, db, _ = env
    async with db.session() as s:
        s.add_all(
            [
                Candidate(
                    sp_id=7001,
                    name="Gisella  Terzolo",
                    name_key="gisella terzolo",
                    email="g@x.test",
                    applied_on=date(2026, 3, 1),
                ),
                Candidate(
                    sp_id=7002,
                    name="Gisella Terzolo",
                    name_key="gisella terzolo",
                    email="g@x.test",
                    applied_on=date(2026, 9, 22),
                ),
            ]
        )
    result = await call(registry, "ficha_candidato", nombre="Gisella Terzolo")
    assert result.status.value == "ok"
    assert result.summary["candidato_id"] == 7002 and result.summary["otras_candidaturas_de_la_misma_persona"] == 1


async def test_requirements_with_exclusion(env: Any) -> None:
    """«Cocina pero sin inglés»: fuera quien lo tiene en metadatos o en el CV, contando aparte el caso del CV."""
    registry, db, _ = env
    async with db.session() as s:
        s.add_all(
            [
                Candidate(
                    sp_id=9101,
                    name="Uno",
                    name_key="uno",
                    department="Cocina",
                    department_key="cocina",
                    experience="Cocinero",
                    languages="Inglés B2",
                ),
                Candidate(
                    sp_id=9102,
                    name="Dos",
                    name_key="dos",
                    department="Cocina",
                    department_key="cocina",
                    experience="Cocinero",
                ),
                CvText(document_id=9102, candidate_id=9102, status="ok", text="Speaks English fluently"),
                Candidate(
                    sp_id=9103,
                    name="Tres",
                    name_key="tres",
                    department="Cocina",
                    department_key="cocina",
                    experience="Ayudante de cocina",
                ),
            ]
        )
    result = await call(
        registry,
        "buscar_candidatos",
        departamento="Cocina",
        requisitos=[{"termino": "cocina"}],
        excluir=[{"termino": "inglés"}],
    )
    assert [m["nombre"] for m in result.summary["muestra"]] == ["Tres"]
    assert result.summary["excluidas_solo_por_el_texto_del_cv"] == 1


async def test_mailbox_comes_from_env_in_development_and_from_the_login_with_msal(env: Any) -> None:
    """Hoy el buzón es el del .env; con MSAL será el de la cuenta con la que se inicia sesión."""
    from mia.modules.rrhh.correo.mailbox import resolve_mailbox  # noqa: PLC0415
    from mia.settings import MailSettings  # noqa: PLC0415

    dev = UserContext("u", "Enrique", email="enrique@sbc.test", roles=frozenset({"mia.admin"}))
    configured = MailSettings(mailbox="rrhh@sbc.test")
    assert resolve_mailbox(configured, dev) == "rrhh@sbc.test"  # el mismo para todos, tal como se declara
    per_user = MailSettings(mailbox="rrhh@sbc.test", mailbox_source="user")
    assert resolve_mailbox(per_user, dev) == "enrique@sbc.test"  # el del usuario, aunque haya uno configurado
    assert resolve_mailbox(per_user, UserContext("x", "Sin correo")) is None


async def test_each_user_only_reaches_their_own_mailbox_and_drafts_do_not_travel(env: Any) -> None:
    from mia.modules.rrhh.correo.mailbox import resolve_mailbox  # noqa: PLC0415

    _, db, settings = env
    per_user = settings.model_copy(update={"mail": settings.mail.model_copy(update={"mailbox_source": "user"})})
    paths: list[str] = []
    fake = _FakeGraph()

    def spy(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return fake.handler(request)

    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(spy))
    registry = build_registry(db, settings=per_user, graph=graph)
    ana = UserContext("a", "Ana", email="ana@sbc.test", roles=frozenset({"mia.admin"}))
    luis = UserContext("l", "Luis", email="luis@sbc.test", roles=frozenset({"mia.admin"}))
    nobody = UserContext("n", "Sin cuenta", roles=frozenset({"mia.admin"}))

    async def as_user(user: UserContext, name: str, state: dict[str, Any], message: str = "", rid: str = "r", **a: Any):
        ctx = ToolContext(user=user, request_id=rid, now=NOW, session_state=state, user_message=message)
        return (await registry.execute(ToolCall("c", name, json.dumps(a)), ctx)).result

    state: dict[str, Any] = {}
    assert (await as_user(ana, "correos_sin_leer", state)).status is ToolStatus.OK
    assert any("ana%40sbc.test" in p or "ana@sbc.test" in p for p in paths) and not any("luis" in p for p in paths)
    assert (await as_user(nobody, "correos_sin_leer", {})).status is ToolStatus.SOURCE_UNAVAILABLE
    await as_user(ana, "preparar_respuesta", state, ref="c1", texto="Recibido.", rid="t1")
    # Luis, aunque compartiera la sesión, no puede enviar un borrador del buzón de Ana.
    blocked = await as_user(luis, "enviar_borrador", state, message="Sí, envíalo", rid="t2", borrador="b1")
    assert blocked.status is ToolStatus.PERMISSION_DENIED and fake.sent == []
    assert resolve_mailbox(per_user.mail, ana) == "ana@sbc.test"
    await graph.aclose()


def test_html_mail_becomes_clean_readable_text() -> None:
    """Fallo real: el correo de Power Automate se veía como cientos de líneas de CSS en una sola línea."""
    from mia.text import html_to_text  # noqa: PLC0415

    html = (
        "<html><head><style>table {width:640px} @media only screen {.a{padding:1px}}</style></head><body>"
        '<div style="display:none;max-height:0">Texto previo oculto &#847; &#847;</div>'
        "<table><tr><td><h1>1 of your flow(s) have failed</h1></td></tr><tr><td><p>Hola Enrique,</p>"
        "<p>Tu flujo <b>Aprobaciones</b> ha fallado.</p><ul><li>Acción: Enviar correo</li><li>Error: 401</li></ul>"
        '<a href="https://make.powerautomate.com/runs">Ver detalles</a></td></tr></table></body></html>'
    )
    text = html_to_text(html)
    assert "width:640px" not in text and "@media" not in text and "oculto" not in text
    assert text.splitlines()[0] == "1 of your flow(s) have failed"
    assert "Hola Enrique,\n\nTu flujo Aprobaciones ha fallado." in text
    assert "- Acción: Enviar correo\n- Error: 401" in text
    assert "Ver detalles (https://make.powerautomate.com/runs)" in text


class _Services:
    """Lo mínimo de Services que usan las acciones de correo de la pantalla."""

    def __init__(
        self, registry: ToolRegistry, db: Any, settings: Any, llm_text: str = "Hola,\n\nGracias.\n\nUn saludo,\nEnrique"
    ) -> None:
        from types import SimpleNamespace  # noqa: PLC0415

        from mia.llm import LLMCompleted, TextDelta  # noqa: PLC0415

        class _LLM:
            async def stream(self, request: Any):
                self.last_prompt = request.messages[-1].content
                yield TextDelta(llm_text)
                yield LLMCompleted()

        self.engine = SimpleNamespace(tools=registry)
        self.db, self.settings, self.llm = db, settings, _LLM()


async def test_screen_mail_actions_open_propose_draft_and_send(env: Any) -> None:
    from mia.api.mail_actions import execute_mail_action  # noqa: PLC0415

    _, db, settings = env
    fake = _FakeGraph()
    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(fake.handler))
    registry = build_registry(db, settings=settings, graph=graph)
    services = _Services(registry, db, settings)
    admin = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
    listing_state: dict[str, Any] = {}
    await call(registry, "correos_sin_leer", listing_state)  # crea la referencia c1 en la sesión
    from mia.data.models import ConversationSession  # noqa: PLC0415

    async with db.session() as s:
        s.add(ConversationSession(id="s1", user_id="u", state=listing_state))

    opened = await execute_mail_action(services, admin, "open", {"session_id": "s1", "ref": "c1"})
    assert (
        opened["ok"] and opened["message"]["text"] == "Hola & gracias" and opened["message"]["subject"] == "Solicitud"
    )
    proposed = await execute_mail_action(
        services, admin, "propose", {"session_id": "s1", "ref": "c1", "instrucciones": "dile que lo vemos el lunes"}
    )
    assert proposed["texto"].startswith("Hola,") and "dile que lo vemos el lunes" in services.llm.last_prompt
    assert "Hola & gracias" in services.llm.last_prompt and "Firma como: Enrique" in services.llm.last_prompt
    saved = await execute_mail_action(
        services, admin, "draft", {"session_id": "s1", "ref": "c1", "texto": proposed["texto"]}
    )
    assert saved["ok"] and saved["draft"]["borrador"] == "b1" and fake.sent == []
    edited = await execute_mail_action(
        services, admin, "update", {"session_id": "s1", "borrador": "b1", "texto": "Nuevo texto"}
    )
    assert edited["ok"] and fake.patched
    sent = await execute_mail_action(services, admin, "send", {"session_id": "s1", "borrador": "b1"})
    assert sent["ok"] and len(fake.sent) == 1  # pulsar «Sí, enviar» es la confirmación explícita
    again = await execute_mail_action(services, admin, "send", {"session_id": "s1", "borrador": "b1"})
    assert not again["ok"] and len(fake.sent) == 1  # no se envía dos veces
    await graph.aclose()


async def test_screen_mail_actions_keep_the_safeguards(env: Any) -> None:
    from mia.api.mail_actions import execute_mail_action  # noqa: PLC0415
    from mia.data.models import ConversationSession  # noqa: PLC0415
    from mia.data.repositories import SessionNotOwnedError  # noqa: PLC0415

    _, db, settings = env
    fake = _FakeGraph(recipient="do_not_reply@sbc.test")  # el destinatario es un no-reply
    graph = GraphClient(StaticTokenProvider(), transport=httpx.MockTransport(fake.handler))
    registry = build_registry(db, settings=settings, graph=graph)
    services = _Services(registry, db, settings)
    admin = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
    state: dict[str, Any] = {}
    await call(registry, "correos_sin_leer", state)
    async with db.session() as s:
        s.add(ConversationSession(id="s2", user_id="u", state=state))
    await execute_mail_action(services, admin, "draft", {"session_id": "s2", "ref": "c1", "texto": "Recibido."})
    blocked = await execute_mail_action(services, admin, "send", {"session_id": "s2", "borrador": "b1"})
    assert not blocked["ok"] and fake.sent == []  # bloqueo de no-reply en código, también desde la pantalla
    other = UserContext("x", "Otra persona", roles=frozenset({"mia.admin"}))
    with pytest.raises(SessionNotOwnedError):
        await execute_mail_action(services, other, "open", {"session_id": "s2", "ref": "c1"})
    unknown = await execute_mail_action(services, admin, "open", {"session_id": "s2", "ref": "c99"})
    assert not unknown["ok"]
    await graph.aclose()


def test_noreply_addresses_are_recognised_with_any_separator() -> None:
    """Fallo real: el buzón recibe de «do_not_reply@…» (guiones bajos) y no se bloqueaba."""
    from mia.modules.rrhh.correo.tools import _NOREPLY  # noqa: PLC0415

    for address in (
        "do_not_reply@sunsetbeachclub.com",
        "PowerAutomateNoReply@microsoft.com",
        "no-reply@x.com",
        "noreply@x.com",
        "no.responder@x.es",
        "do-not-reply@x.com",
    ):
        assert _NOREPLY.search(address), address
    for address in ("ana@x.es", "reply.team@x.es", "notify@x.es"):
        assert not _NOREPLY.search(address), address


async def test_documents_can_be_opened_from_the_screen_according_to_permissions(env: Any, monkeypatch: Any) -> None:
    """El antiguo ofrecía «abrir el documento» en el listado; el PDF de nómina lleva importes: solo con ese permiso."""
    from mia.auth.context import ROLE_PERMISSIONS, Permission  # noqa: PLC0415

    registry, _, _ = env
    result = await call(registry, "nominas_persona", empleado_id=1)
    docs = result.presentation["documents"]
    assert docs and all(d["url"].startswith("/api/documents/nomina/") and d["kind"] == "nomina" for d in docs)
    assert docs[0]["date"] == "2026-08"  # la más reciente primero

    monkeypatch.setitem(
        ROLE_PERMISSIONS, "test.lectura", frozenset({Permission.NOMINAS_LEER, Permission.EMPLEADOS_LEER})
    )
    ctx = ToolContext(
        user=UserContext("l", "Lectura", roles=frozenset({"test.lectura"})), request_id="r", now=NOW, session_state={}
    )
    limited = (await registry.execute(ToolCall("c", "nominas_persona", json.dumps({"empleado_id": 1})), ctx)).result
    assert limited.status is ToolStatus.OK and "documents" not in limited.presentation


def test_documents_reach_the_screen_and_nothing_else_leaks() -> None:
    from mia.api.legacy_view import legacy_view  # noqa: PLC0415

    table = {
        "type": "table",
        "title": "Nóminas",
        "columns": ["Periodo"],
        "rows": [["2026-08"]],
        "documents": [
            {
                "kind": "nomina",
                "title": "Agosto",
                "subtitle": "mensual",
                "date": "2026-08",
                "url": "/api/documents/nomina/1",
                "secreto": "x",
            }
        ],
    }
    data, _ = legacy_view([table])
    assert data["documents"] == [
        {
            "kind": "nomina",
            "title": "Agosto",
            "subtitle": "mensual",
            "date": "2026-08",
            "url": "/api/documents/nomina/1",
        }
    ]


def test_payslip_kinds_follow_the_previous_systems_priority() -> None:
    """MesNomina manda sobre el nombre del fichero (como el antiguo): un mes real es nómina mensual aunque el nombre diga extra."""
    from mia.data import Payslip  # noqa: PLC0415
    from mia.modules.rrhh.nominas.tools import document_kind  # noqa: PLC0415

    def kind(file_name: str, label: str | None, **kw: Any) -> str:
        return document_kind(Payslip(sp_id=1, person_key="p", file_name=file_name, label=label, **kw))

    assert kind("2026-08_Agosto.pdf", "Agosto") == "nómina mensual"
    assert kind("2025-71_Extra Julio.pdf", "Extra Julio") == "paga extra"
    assert kind("2026-07_Extra.pdf", "Julio") == "nómina mensual"  # el mes de MesNomina manda
    assert kind("Certificado retenciones 2025.pdf", None) == "certificado de retenciones"
    assert kind("Bolsa vacaciones 2025.pdf", None) == "bolsa de vacaciones"
    assert kind("2026-03.pdf", None) == "nómina mensual"
    assert kind("Otra cosa.pdf", None) == "otro documento"


async def test_cv_is_found_on_another_application_of_the_same_person(env: Any) -> None:
    """Caso real: «resúmeme el CV de Gisella Terzolo» → «no hay un CV» (el texto colgaba de otra candidatura suya)."""
    registry, db, _ = env
    async with db.session() as s:
        s.add_all(
            [
                Candidate(
                    sp_id=7101,
                    name="Gisella Terzolo",
                    name_key="gisella terzolo",
                    email="g@x.test",
                    applied_on=date(2026, 3, 1),
                ),
                CvText(
                    document_id=71,
                    candidate_id=7101,
                    status="ok",
                    text="Más de 20 años de experiencia; supervisora en Miami.",
                ),
                Candidate(
                    sp_id=7102,
                    name="Gisella Terzolo",
                    name_key="gisella terzolo",
                    email="g@x.test",
                    applied_on=date(2026, 9, 22),
                ),  # la más reciente, SIN texto de CV propio
            ]
        )
    result = await call(registry, "ficha_candidato", nombre="Gisella Terzolo")
    assert result.status.value == "ok" and result.summary["candidato_id"] == 7102
    assert "supervisora en Miami" in result.summary["cv"]["extracto"]
