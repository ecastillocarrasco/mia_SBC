"""Regresión del módulo de correo (mejora pedida por el usuario): ``correos_sin_leer`` dejó de ser
lo único disponible para "muéstrame mis últimos correos" (antes se usaba, por error, como sustituto
general y sólo mostraba los no leídos). Cubre las herramientas nuevas (``correos_recientes``,
``correos_enviados``, ``hilo_correo``), el enlace de descarga de adjuntos en ``leer_correo`` y el
endpoint real que sirve esos adjuntos.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from mia.api.routes.mail import mail_attachment, mail_unread
from mia.auth import Permission, UserContext
from mia.connectors.graph import GraphClient
from mia.connectors.sharepoint import StaticTokenProvider
from mia.conversation.tools import ToolContext, ToolRegistry, ToolStatus
from mia.llm import ToolCall
from mia.modules.correo.tools import enviados, hilo, leer, pendientes, recientes
from mia.modules.correo.tools import register as register_mail
from mia.modules.registry import build_registry
from mia.modules.rrhh.common import Deps
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


async def test_same_batch_mail_open_waits_for_real_listing_references():
    async def handler(request):
        await asyncio.sleep(0)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"value": [_message("m1", read=True)]})
        return httpx.Response(
            200, json={**_message("m1", read=True), "body": {"contentType": "text", "content": "Synthetic body"}}
        )

    graph = _graph(handler)
    registry = ToolRegistry()
    register_mail(registry, _deps(graph))
    try:
        results = await registry.execute_all(
            [
                ToolCall("list", "correos_recientes", '{"limite":1}'),
                ToolCall("open", "leer_correo", '{"ref":"c1"}'),
            ],
            _ctx(),
        )
        assert all(result.result.status is ToolStatus.OK for result in results)
        assert results[1].result.summary["texto"] == "Synthetic body"
    finally:
        await graph.aclose()


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


async def test_correos_recientes_expands_attachment_names_and_types() -> None:
    """Petición del usuario: el aviso de correo nuevo debe poder anunciar nombre y tipo de los
    adjuntos, así que ``correos_recientes`` (la herramienta que alimenta /api/mail/notifications/poll)
    tiene que pedirlos a Graph en la misma llamada, sin una petición aparte por mensaje."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["expand"] = request.url.params.get("$expand") or ""
        message = _message("m1", read=True)
        message["hasAttachments"] = True
        message["attachments"] = [{"name": "informe.pdf", "contentType": "application/pdf"}]
        return httpx.Response(200, json={"value": [message]})

    graph = _graph(handler)
    tool = recientes(_deps(graph))
    result = await tool.handler(tool.params(limite=10), _ctx())
    await graph.aclose()

    assert "attachments" in seen["expand"]
    assert result.summary["correos"][0]["adjuntos_detalle"] == [{"nombre": "informe.pdf", "tipo": "PDF"}]


async def test_correos_recientes_without_attachments_has_no_adjuntos_detalle() -> None:
    graph = _graph(lambda r: httpx.Response(200, json={"value": [_message("m1", read=True)]}))
    tool = recientes(_deps(graph))
    result = await tool.handler(tool.params(limite=10), _ctx())
    await graph.aclose()

    assert "adjuntos_detalle" not in result.summary["correos"][0]


async def test_correos_sin_leer_still_filters_unread_only() -> None:
    """Guarda de regresión del propio contrato: ``correos_sin_leer`` sigue siendo el filtro
    explícito, no una alternativa de ``correos_recientes``."""

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


# ------------------------------------------------------------------ leer_correo: apertura directa
#
# Regresión real: con el correo ya abierto en un turno anterior de la misma sesión, el LLM
# respondía "ya está abierto, el contenido se muestra arriba" SIN volver a llamar a
# leer_correo -- sin herramienta ejecutada no hay presentación ese turno y la interfaz no
# muestra nada (solo ese texto). "Abre el correo cN" es inequívoco: se resuelve de forma
# determinista (direct_read_arguments), igual que el resumen de correos o el salario directo.


def test_leer_correo_direct_read_arguments_matches_an_explicit_open_request() -> None:
    tool = leer(_deps(_graph(lambda request: httpx.Response(200, json={}))))
    assert tool.direct_read_arguments(_ctx_with_message("Abre el correo c1")) == {"ref": "c1"}
    assert tool.direct_read_arguments(_ctx_with_message("muéstrame el correo c2")) == {"ref": "c2"}
    assert tool.direct_read_arguments(_ctx_with_message("lee el mensaje c3")) == {"ref": "c3"}
    # Peticiones compuestas o ambiguas: el planner decide, no el matcher determinista.
    assert tool.direct_read_arguments(_ctx_with_message("abre el correo c1 y resúmelo")) is None
    assert tool.direct_read_arguments(_ctx_with_message("quién me ha escrito")) is None


def _ctx_with_message(message: str) -> ToolContext:
    return ToolContext(
        user=ADMIN, request_id="req-1", now=datetime(2026, 10, 20, 9, 0), session_state={}, user_message=message
    )


async def test_leer_correo_returns_a_verified_answer_for_a_direct_open_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json={"value": []})
        return httpx.Response(
            200,
            json={
                "subject": "Informe mensual",
                "from": {"emailAddress": {"name": "Ana", "address": "ana@sbc.test"}},
                "toRecipients": [],
                "receivedDateTime": "2026-10-19T10:00:00Z",
                "body": {"content": "Contenido del correo.", "contentType": "text"},
                "hasAttachments": False,
            },
        )

    graph = _graph(handler)
    ctx = ToolContext(
        user=ADMIN,
        request_id="req-1",
        now=datetime(2026, 10, 20, 9, 0),
        session_state={"correos": {"c1": "msg-1"}},
        user_message="Abre el correo c1",
    )
    tool = leer(_deps(graph))
    result = await tool.handler(tool.params(ref="c1"), ctx)
    await graph.aclose()

    assert result.verified_answer is not None
    assert "Ana" in result.verified_answer
    assert result.presentation == {"type": "mail", **result.summary}


async def test_leer_correo_has_no_verified_answer_when_the_llm_chose_to_call_it() -> None:
    """Fuera del patrón de apertura directa, la narrativa la sigue construyendo el LLM."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json={"value": []})
        return httpx.Response(
            200,
            json={
                "subject": "Informe mensual",
                "from": {"emailAddress": {"name": "Ana", "address": "ana@sbc.test"}},
                "toRecipients": [],
                "receivedDateTime": "2026-10-19T10:00:00Z",
                "body": {"content": "Contenido del correo.", "contentType": "text"},
                "hasAttachments": False,
            },
        )

    graph = _graph(handler)
    ctx = ToolContext(
        user=ADMIN,
        request_id="req-1",
        now=datetime(2026, 10, 20, 9, 0),
        session_state={"correos": {"c1": "msg-1"}},
        user_message="resume el correo c1 y dime si requiere respuesta",
    )
    tool = leer(_deps(graph))
    result = await tool.handler(tool.params(ref="c1"), ctx)
    await graph.aclose()

    assert result.verified_answer is None


# ------------------------------------------------------------------ buzon compartido (OBO delegado)

MC_SALAS = UserContext(
    "mc-salas-oid",
    "Mª Carmen Salas",
    roles=frozenset({"mia.rrhh"}),
    auth_method="entra",
    email="mc.salas@sunsetbeachclub.com",
    graph_assertion="caller-own-api-token",
)


def _ctx_entra(user: UserContext = MC_SALAS) -> ToolContext:
    return ToolContext(user=user, request_id="req-1", now=datetime(2026, 10, 20, 9, 0), session_state={})


async def _fake_delegated_token(user: UserContext, *, force_refresh: bool = False) -> str:
    """Sustituye el intercambio OBO real (MSAL + certificado) por un token de prueba: estos tests
    verifican el enrutado del buzón y la gestión del 200/403 de Graph, no el propio protocolo OBO
    (eso lo cubre graph.py / MSAL, no mIA)."""
    return "fake-delegated-graph-token"


async def test_recientes_cross_mailbox_uses_the_callers_own_obo_token_against_the_target_mailbox() -> None:
    """mc.salas tiene Full Access delegado (ya concedido en Exchange) sobre RRHH@sunsetbeachclub.com.
    Al pedir buzon="RRHH@sunsetbeachclub.com", Graph debe recibir la petición sobre ESE buzón usando
    el token OBO de mc.salas -- no hay catálogo ni allow-list dentro de mIA, es Exchange quien decide."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"value": [_message("m1", read=False)]})

    graph = _graph(handler)
    graph._delegated_token = _fake_delegated_token  # type: ignore[method-assign]
    tool = recientes(_deps(graph))
    result = await tool.handler(tool.params(buzon="RRHH@sunsetbeachclub.com"), _ctx_entra())
    await graph.aclose()

    assert seen["path"] == "/v1.0/users/RRHH@sunsetbeachclub.com/mailFolders/inbox/messages"
    assert result.status is ToolStatus.OK
    assert result.summary["correos_mostrados"] == 1


async def test_recientes_cross_mailbox_denied_by_exchange_shows_a_clear_message_without_graph_internals() -> None:
    """Sin delegación concedida, Exchange responde 403 y GraphError lo traduce a un mensaje claro
    para la persona -- sin volcar el cuerpo/JSON interno de la respuesta de Graph."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": {"code": "ErrorAccessDenied", "innerError": {"request-id": "abc-123"}}}
        )

    graph = _graph(handler)
    graph._delegated_token = _fake_delegated_token  # type: ignore[method-assign]
    tool = recientes(_deps(graph))
    result = await tool.handler(tool.params(buzon="RRHH@sunsetbeachclub.com"), _ctx_entra())
    await graph.aclose()

    assert result.status is ToolStatus.SOURCE_UNAVAILABLE
    assert "permiso" in result.summary.lower()
    assert "ErrorAccessDenied" not in result.summary
    assert "request-id" not in result.summary


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

    user_without_mail = UserContext("u2", "Sin permiso", roles=frozenset())
    db = await fresh_database(tmp_path, "mail_attachment_denied.db")
    graph = _graph(lambda r: httpx.Response(500))

    with pytest.raises(HTTPException) as excinfo:
        await mail_attachment("msg-1", "att-1", _services(graph, db), user_without_mail)
    await graph.aclose()

    assert excinfo.value.status_code == 403


async def test_mail_attachment_route_404s_when_graph_has_nothing(tmp_path: Path) -> None:

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


async def test_mail_unread_route_is_available_to_any_recognized_role(tmp_path: Path) -> None:
    """CORREO_LEER es universal para cualquier rol reconocido, no un privilegio de "mia.rrhh":
    "Legal" no lo lleva declarado en ROLE_PERMISSIONS y debe poder usarlo igual."""

    user_legal = UserContext("u2", "Legal", roles=frozenset({"Legal"}))
    db = await fresh_database(tmp_path, "mail_unread_legal.db")
    settings = Settings(_env_file=None, environment=Environment.TEST, mail={"mailbox": "rrhh@sbc.test"})
    graph = _graph(lambda r: httpx.Response(200, json={"value": []}))
    registry = build_registry(db, settings=settings, graph=graph)
    services = SimpleNamespace(engine=SimpleNamespace(tools=registry))

    result = await mail_unread(services, user_legal)
    await graph.aclose()
    await db.dispose()

    assert result["sin_leer_mostrados"] == 0


async def test_mail_unread_route_denies_a_user_without_any_recognized_role(tmp_path: Path) -> None:
    """Sin ningún rol reconocido no hay acceso de ningún tipo, ni siquiera a correo (ver
    UserContext.permissions): 403, no un resultado vacío."""

    user_without_role = UserContext("u3", "Sin rol", roles=frozenset())
    db = await fresh_database(tmp_path, "mail_unread_denied.db")
    settings = Settings(_env_file=None, environment=Environment.TEST, mail={"mailbox": "rrhh@sbc.test"})
    graph = _graph(lambda r: httpx.Response(200, json={"value": []}))
    registry = build_registry(db, settings=settings, graph=graph)
    services = SimpleNamespace(engine=SimpleNamespace(tools=registry))

    with pytest.raises(HTTPException) as excinfo:
        await mail_unread(services, user_without_role)
    await graph.aclose()
    await db.dispose()

    assert excinfo.value.status_code == 403


def test_admin_has_correo_leer_permission() -> None:
    """Control del fixture: evita que los tests de arriba pasen "por accidente" si ``ADMIN`` no
    tuviera el permiso que la ruta exige."""
    assert ADMIN.has(Permission.CORREO_LEER)
