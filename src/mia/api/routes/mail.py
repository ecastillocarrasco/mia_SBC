"""Acciones de correo de la pantalla: ver mia/api/mail_actions.py."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from mia.api.deps import ServicesDep, UserDep
from mia.api.mail_actions import ACTIONS, MailActionError, execute_mail_action
from mia.auth import Permission
from mia.connectors.graph import GraphClient, GraphError
from mia.conversation.tools import ToolContext, ToolStatus
from mia.data.repositories import AuditRepository
from mia.llm import ToolCall
from mia.modules.correo.mailbox import resolve_mailbox
from mia.modules.correo.tools import MAX_ATTACHMENT_BYTES
from mia.observability import current_request_id, get_logger

router = APIRouter(tags=["correo"], include_in_schema=False)
log = get_logger(__name__)


@router.get("/api/mail/unread")
async def mail_unread(
    services: ServicesDep, user: UserDep, limite: int = 10, buzon: str | None = None
) -> dict[str, Any]:
    """Comprobación ligera para sondeo periódico (mia-desktop, cada pocos minutos): invoca la
    herramienta ``correos_sin_leer`` directamente, sin pasar por el LLM -- determinista y barata,
    pensada para preguntarse con frecuencia sin gastar ningún turno de conversación."""
    ctx = ToolContext(user=user, request_id=current_request_id(), now=datetime.now(UTC), session_state={})
    execution = await services.engine.tools.execute(
        ToolCall("mail-poll", "correos_sin_leer", json.dumps({"limite": limite, "buzon": buzon})), ctx
    )
    result = execution.result
    if result.status is ToolStatus.PERMISSION_DENIED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para leer el correo")
    if result.status is not ToolStatus.OK:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No se ha podido comprobar el correo")
    return result.summary


@router.get("/api/mail/notifications/poll")
async def mail_notification_poll(
    services: ServicesDep, user: UserDep, limite: int = 10, buzon: str | None = None
) -> dict[str, Any]:
    """Sondeo de mensajes recientes de la bandeja de entrada, estén leídos o no.

    La notificación debe detectar cualquier mensaje entrante (nuevo, reenviado o respuesta), aunque
    Outlook lo haya marcado como leído antes del siguiente intervalo. El cliente compara fechas y
    huellas locales para no volver a notificar los mensajes que ya estaban al iniciar.
    """
    ctx = ToolContext(user=user, request_id=current_request_id(), now=datetime.now(UTC), session_state={})
    execution = await services.engine.tools.execute(
        ToolCall(
            "mail-notification-poll",
            "correos_recientes",
            json.dumps({"limite": limite, "buzon": buzon, "incluir_texto": False}),
        ),
        ctx,
    )
    result = execution.result
    if result.status is ToolStatus.PERMISSION_DENIED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para leer el correo")
    if result.status is not ToolStatus.OK:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No se ha podido comprobar el correo")
    # El cliente solo necesita una huella mínima para detectar cambios y presentar el aviso; no
    # enviar previews ni cuerpo del correo en cada sondeo.
    rows = result.summary.get("correos", []) if isinstance(result.summary, dict) else []
    refs = ctx.session_state.get("correos", {})
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        message_id = refs.get(row.get("ref"))
        opaque_key = hashlib.sha256(f"{user.user_id}:{message_id}".encode()).hexdigest()[:24] if message_id else None
        items.append({
            "de": row.get("de"),
            "asunto": row.get("asunto"),
            "recibido": row.get("recibido"),
            "huella": opaque_key,
        })
    # Diagnóstico sin remitentes, asuntos, identificadores ni contenido: confirma si Graph
    # realmente devuelve mensajes al sondeo cuando el cliente no muestra el aviso.
    log.info(
        "mail.notification_poll_result",
        message_count=len(items),
        fingerprint_count=sum(bool(item.get("huella")) for item in items),
    )
    return {"correos": items}


@router.post("/api/mail/{action}")
@router.post("/api/mia/mail/{action}")
async def mail_action(action: str, body: dict[str, Any], services: ServicesDep, user: UserDep) -> dict[str, Any]:
    if action not in ACTIONS:
        raise HTTPException(404, "Acción de correo desconocida")
    try:
        return await execute_mail_action(services, user, action, body)
    except MailActionError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/mail/attachment/{message_id}/{attachment_id}")
async def mail_attachment(
    message_id: str, attachment_id: str, services: ServicesDep, user: UserDep, buzon: str | None = None
) -> Response:
    """Descarga el adjunto del buzón asociado a la referencia; si es compartido, Graph comprueba el permiso OBO."""
    if not user.has(Permission.CORREO_LEER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para abrir adjuntos de correo")
    if services.graph is None or not services.settings:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El buzón de correo no está configurado")
    if buzon and buzon.strip():
        mailbox = buzon.strip()
    elif user.auth_method == "entra":
        mailbox = user.user_id
    else:
        mailbox = resolve_mailbox(services.settings.mail, user)
    if not mailbox:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El buzón de correo no está configurado")
    personal_mailbox = user.user_id if user.auth_method == "entra" else resolve_mailbox(services.settings.mail, user)
    if buzon and user.auth_method != "entra" and mailbox != personal_mailbox:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Los buzones compartidos requieren autenticación delegada")
    attachment: dict[str, Any] | None = None
    outcome = "ok"
    try:
        # Sin "$select": Graph rechaza "contentBytes" en el $select de /attachments (HTTP 400,
        # "Could not find a property named 'contentBytes' on type 'microsoft.graph.attachment'") —
        # esa propiedad solo existe en el tipo derivado fileAttachment. Pedir el adjunto sin
        # restricciones sirve el tipo real ya resuelto, con todas sus propiedades.
        attachment = await services.graph.request(
            "GET", f"{GraphClient.user_path(mailbox)}/messages/{message_id}/attachments/{attachment_id}", user=user
        )
        if not attachment.get("contentBytes"):
            outcome = "not_found"
    except GraphError:
        outcome = "not_found"
    async with services.db.session() as db:
        await AuditRepository(db).record(
            user_id=user.user_id,
            action="descarga:adjunto_correo",
            resource="correo",
            outcome=outcome,
            request_id=current_request_id(),
            detail={"message_id": message_id, "attachment_id": attachment_id},
        )
    if outcome != "ok" or attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese adjunto no se ha podido descargar")
    if int(attachment.get("size") or 0) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "El adjunto supera el tamaño máximo permitido")
    content = base64.b64decode(attachment["contentBytes"])
    name = str(attachment.get("name") or "adjunto").replace('"', "")
    return Response(
        content,
        media_type=str(attachment.get("contentType") or "application/octet-stream"),
        # "inline" (no "attachment"): igual que /api/documents/{kind}/{id} — permite VER el adjunto en
        # una pestaña (PDF, imagen) cuando el navegador puede, y el propio navegador sigue ofreciendo
        # "Guardar como" para descargarlo. Pedido explícito del usuario: "ver o descargar los adjuntos".
        headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"},
    )
