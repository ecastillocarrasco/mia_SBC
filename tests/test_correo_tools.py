"""Regresión del módulo de correo (mejora pedida por el usuario): ``correos_sin_leer`` dejó de ser
lo único disponible para "muéstrame mis últimos correos" (antes se usaba, por error, como sustituto
general y sólo mostraba los no leídos). Cubre las herramientas nuevas (``correos_recientes``,
``correos_enviados``, ``hilo_correo``), el enlace de descarga de adjuntos en ``leer_correo`` y el
endpoint real que sirve esos adjuntos.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from mia.auth import Permission, UserContext
from mia.connectors.graph import GraphClient
from mia.connectors.sharepoint import StaticTokenProvider
from mia.conversation.tools import ToolContext, ToolStatus
from mia.modules.rrhh import build_registry
from mia.modules.rrhh.common import Deps
from mia.modules.rrhh.correo.tools import enviados, hilo, leer, recientes
from mia.settings import Environment, MailSettings, Settings
from tests.dbutil import fresh_database

ADMIN = UserContext("u1", "Enrique", roles=frozenset({"mia.rrhh"}))


def _ctx() -> ToolContext:
    return ToolContext(user=ADMIN, request_id="req-1", now=datetime(2026, 10, 20, 9, 0), session_state={})


def _deps(graph: GraphClient) -> Deps:
    settings = SimpleNamespace(mail=MailSettings(mailbox="rrhh@sbc.test", send_enabled=False))
    return Deps(db=None, settings=settings, graph=graph)


def _graph(handler) -> GraphClient:
    return GraphClient(tokens=StaticTokenProvider(), transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ correos_recientes (el bug reportado)


async def test_correos_recientes_does_not_filter_by_read_status() -> None:
    """Antes de este cambio, "muéstrame los últimos correos recibidos" acababa usando
    ``correos_sin_leer`` y sólo mostraba los no leídos. ``correos_recientes`` nunca debe mandar
    ``$filter`` por estado de lectura."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["filter"] = request.url.params.get("$filter") or ""
        return httpx.Response(200, json={"value": [_message("m1", read=True), _message("m2", read=False)]})

    graph = _graph(handler)
    tool = recientes(_deps(graph))
    result = await tool.handler(tool.params(limite=10), _ctx())
    await graph.aclose()

    assert seen["filter"] == ""
    assert result.status is ToolStatus.OK
    assert result.summary["correos_mostrados"] == 2


async def test_correos_sin_leer_still_filters_unread_only() -> None:
    """Guarda de regresión del propio contrato: ``correos_sin_leer`` sigue siendo el filtro
    explícito, no una alternativa de ``correos_recientes``."""
    from mia.modules.rrhh.correo.tools import pendientes

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["filter"] = request.url.params.get("$filter") or ""
        return httpx.Response(200, json={"value": [_message("m1", read=False)]})

    graph = _graph(handler)
    tool = pendientes(_deps(graph))
    await tool.handler(tool.params(), _ctx())
    await graph.aclose()

    assert seen["filter"] == "isRead eq false"


# ------------------------------------------------------------------ correos_enviados


async def test_correos_enviados_queries_sent_items_with_recipients() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "m1",
                        "subject": "Vacaciones",
                        "toRecipients": [{"emailAddress": {"address": "ana@sbc.test"}}],
                        "sentDateTime": "2026-10-19T10:00:00Z",
                        "bodyPreview": "Confirmo mis fechas",
                        "hasAttachments": False,
                        "isRead": True,
                        "conversationId": "conv-1",
                    }
                ]
            },
        )

    graph = _graph(handler)
    tool = enviados(_deps(graph))
    result = await tool.handler(tool.params(), _ctx())
    await graph.aclose()

    assert "sentitems" in seen["path"]
    assert result.status is ToolStatus.OK
    row = result.presentation["mail_rows"][0]
    assert row["from"] == "ana@sbc.test"  # en enviados, "from" muestra el destinatario


# ------------------------------------------------------------------ hilo_correo


async def test_hilo_correo_fetches_the_whole_conversation_by_id() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/messages/m1"):
            return httpx.Response(200, json={"conversationId": "conv-o'brien"})
        return httpx.Response(
            200,
            json={"value": [_message("m1", read=True), _message("m2", read=True)]},
        )

    graph = _graph(handler)
    ctx = _ctx()
    ctx.session_state["correos"] = {"c1": "m1"}
    tool = hilo(_deps(graph))
    result = await tool.handler(tool.params(ref="c1"), ctx)
    await graph.aclose()

    assert result.status is ToolStatus.OK
    assert result.presentation["type"] == "mail_thread"
    assert result.summary["mensajes_en_el_hilo"] == 2
    thread_request = calls[-1]
    # Escapado OData: una comilla simple se duplica, nunca se interpola sin más.
    assert "conv-o''brien" in thread_request.url.params["$filter"]


async def test_hilo_correo_requires_a_known_reference() -> None:
    tool = hilo(_deps(_graph(lambda r: httpx.Response(500))))
    result = await tool.handler(tool.params(ref="c99"), _ctx())
    assert result.status is ToolStatus.NOT_FOUND


# ------------------------------------------------------------------ leer_correo: enlaces de adjuntos


async def test_leer_correo_exposes_a_download_url_only_for_file_attachments() -> None:
    """Regresión real: Microsoft Graph devuelve HTTP 400 ("Could not find a property named
    'contentBytes' on type 'microsoft.graph.attachment'") si el ``$select`` de /attachments (la
    colección) incluye ``contentBytes`` — esa propiedad solo existe en el tipo derivado
    fileAttachment. El listado se pide SIN contentBytes; el contenido se obtiene con una segunda
    petición por adjunto, sin ``$select``."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/attachments"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "att-1",
                            "name": "informe.pdf",
                            "size": 100,
                            "contentType": "application/pdf",
                            "@odata.type": "#microsoft.graph.fileAttachment",
                        },
                        {
                            "id": "att-2",
                            "name": "correo reenviado",
                            "@odata.type": "#microsoft.graph.itemAttachment",
                        },
                    ]
                },
            )
        if request.url.path.endswith("/attachments/att-1"):
            return httpx.Response(
                200,
                json={
                    "id": "att-1",
                    "name": "informe.pdf",
                    "size": 100,
                    "contentType": "application/pdf",
                    "contentBytes": "SG9sYQ==",
                    "@odata.type": "#microsoft.graph.fileAttachment",
                },
            )
        return httpx.Response(
            200,
            json={
                "subject": "Informe mensual",
                "from": {"emailAddress": {"name": "Ana", "address": "ana@sbc.test"}},
                "toRecipients": [],
                "receivedDateTime": "2026-10-19T10:00:00Z",
                "body": {"content": "Adjunto el informe.", "contentType": "text"},
                "hasAttachments": True,
            },
        )

    graph = _graph(handler)
    ctx = _ctx()
    ctx.session_state["correos"] = {"c1": "msg-1"}
    tool = leer(_deps(graph))
    result = await tool.handler(tool.params(ref="c1"), ctx)
    await graph.aclose()

    adjuntos = result.summary["adjuntos"]
    assert adjuntos[0]["url"] == "/api/mail/attachment/msg-1/att-1"
    assert adjuntos[1]["url"] is None

    listing_request = next(r for r in requests if r.url.path.endswith("/attachments"))
    assert "contentBytes" not in (listing_request.url.params.get("$select") or "")
    single_request = next(r for r in requests if r.url.path.endswith("/attachments/att-1"))
    assert "$select" not in single_request.url.params


def _message(msg_id: str, *, read: bool) -> dict[str, object]:
    return {
        "id": msg_id,
        "subject": "Asunto",
        "from": {"emailAddress": {"name": "Ana", "address": "ana@sbc.test"}},
        "receivedDateTime": "2026-10-19T10:00:00Z",
        "bodyPreview": "Hola",
        "hasAttachments": False,
        "isRead": read,
        "conversationId": "conv-1",
    }


# ------------------------------------------------------------------ GET /api/mail/attachment/{message_id}/{attachment_id}


def _services(graph: GraphClient, db) -> SimpleNamespace:
    return SimpleNamespace(graph=graph, settings=SimpleNamespace(mail=MailSettings(mailbox="rrhh@sbc.test")), db=db)


async def test_mail_attachment_route_downloads_the_real_content(tmp_path: Path) -> None:
    from mia.api.routes.mail import mail_attachment

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/messages/msg-1/attachments/att-1")
        return httpx.Response(
            200,
            json={"name": "informe.pdf", "contentType": "application/pdf", "contentBytes": "aGVsbG8=", "size": 5},
        )

    graph = _graph(handler)
    db = await fresh_database(tmp_path, "mail_attachment.db")
    response = await mail_attachment("msg-1", "att-1", _services(graph, db), ADMIN)
    await graph.aclose()

    assert response.status_code == 200
    assert response.body == b"hello"
    assert response.media_type == "application/pdf"
    assert "informe.pdf" in response.headers["content-disposition"]


async def test_mail_attachment_route_requires_permission(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from mia.api.routes.mail import mail_attachment

    user_without_mail = UserContext("u2", "Sin permiso", roles=frozenset())
    db = await fresh_database(tmp_path, "mail_attachment_denied.db")
    graph = _graph(lambda r: httpx.Response(500))

    with pytest.raises(HTTPException) as excinfo:
        await mail_attachment("msg-1", "att-1", _services(graph, db), user_without_mail)
    await graph.aclose()

    assert excinfo.value.status_code == 403


async def test_mail_attachment_route_404s_when_graph_has_nothing(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from mia.api.routes.mail import mail_attachment

    graph = _graph(lambda r: httpx.Response(404, json={"error": {"message": "not found"}}))
    db = await fresh_database(tmp_path, "mail_attachment_missing.db")

    with pytest.raises(HTTPException) as excinfo:
        await mail_attachment("msg-1", "att-missing", _services(graph, db), ADMIN)
    await graph.aclose()

    assert excinfo.value.status_code == 404


# ------------------------------------------------------------------ GET /api/mail/unread (sondeo periódico)


async def test_mail_unread_route_calls_the_tool_directly_without_an_llm_turn(tmp_path: Path) -> None:
    """mia-desktop sondea esto cada pocos minutos: debe funcionar sin gastar ningún turno de
    conversación (la ruta invoca correos_sin_leer directamente sobre el registro de herramientas)."""
    from mia.api.routes.mail import mail_unread

    graph = _graph(lambda r: httpx.Response(200, json={"value": [_message("m1", read=False)]}))
    db = await fresh_database(tmp_path, "mail_unread.db")
    settings = Settings(_env_file=None, environment=Environment.TEST, mail={"mailbox": "rrhh@sbc.test"})
    registry = build_registry(db, settings=settings, graph=graph)
    services = SimpleNamespace(engine=SimpleNamespace(tools=registry))

    result = await mail_unread(services, ADMIN, limite=10)
    await graph.aclose()
    await db.dispose()

    assert result["sin_leer_mostrados"] == 1
    assert result["correos"][0]["asunto"] == "Asunto"


async def test_mail_unread_route_requires_permission(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from mia.api.routes.mail import mail_unread

    user_without_mail = UserContext("u2", "Sin permiso", roles=frozenset())
    db = await fresh_database(tmp_path, "mail_unread_denied.db")
    settings = Settings(_env_file=None, environment=Environment.TEST, mail={"mailbox": "rrhh@sbc.test"})
    registry = build_registry(db, settings=settings, graph=_graph(lambda r: httpx.Response(500)))
    services = SimpleNamespace(engine=SimpleNamespace(tools=registry))

    with pytest.raises(HTTPException) as excinfo:
        await mail_unread(services, user_without_mail)
    await db.dispose()

    assert excinfo.value.status_code == 403


def test_admin_has_correo_leer_permission() -> None:
    """Control del fixture: evita que los tests de arriba pasen "por accidente" si ``ADMIN`` no
    tuviera el permiso que la ruta exige."""
    assert ADMIN.has(Permission.CORREO_LEER)
