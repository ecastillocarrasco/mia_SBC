"""Dominio de correo corporativo por usuario (Microsoft Graph).

COR-001: mIA puede leer, buscar y preparar borradores. Enviar exige que el
borrador se haya preparado en un turno anterior (el usuario lo ha visto) y que el
mensaje actual del usuario lo confirme expresamente. Además, el envío está
desactivado salvo que se habilite en la configuración.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mia.auth import Permission
from mia.connectors.graph import GraphClient, GraphError
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee
from mia.modules.correo.deps import MailDeps
from mia.modules.correo.mailbox import resolve_mailbox
from mia.modules.correo.signature import SIGNATURE_BANNER_CID, MailSignature, build_mail_signature
from mia.observability import get_logger
from mia.text import plain_text

log = get_logger(__name__)

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
"""Límite de tamaño para adjuntos leídos desde Graph."""
SIGNATURE_BANNER_PATH = Path(__file__).with_name("assets") / "signature-banner.png"

KEYWORDS = (
    "correo",
    "correos",
    "email",
    "emails",
    "e-mail",
    "buzon",
    "buzón",
    "bandeja de entrada",
    "mensaje",
    "mensajes",
    "borrador",
    "borradores",
    "responder correo",
    "enviar correo",
    "correo sin leer",
    "correos enviados",
    "elementos enviados",
    "hilo de correo",
    "hilo de correos",
    "conversacion de correo",
    "conversación de correo",
    "ultimos correos",
    "últimos correos",
    "adjunto del correo",
    "adjuntos del correo",
    "descargar adjunto",
)
"""Ver `empleados.tools.KEYWORDS` para el criterio."""

_CONFIRM = re.compile(r"\b(s[ií]|env[ií]a(lo)?|adelante|confirm[oa]|de acuerdo|vale|ok)\b", re.IGNORECASE)
_NOREPLY = re.compile(
    r"no[-_.]?reply|do[-_.]?not[-_.]?reply|no[-_.]?responder|no[-_.]?contestar|no[-_.]?contestes", re.IGNORECASE
)
_DENY = re.compile(r"\b(no|espera|todav[ií]a no|cancela)\b", re.IGNORECASE)
SELECT = "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,isRead,conversationId"
SELECT_SENT = "id,subject,from,toRecipients,sentDateTime,bodyPreview,hasAttachments,isRead,conversationId"


def _plain(body: dict[str, Any] | None) -> str:
    return plain_text(str((body or {}).get("content") or ""), str((body or {}).get("contentType") or "text"))


def _reply_body_html(text: str, quoted_body: dict[str, Any] | None = None, signature_html: str = "") -> str:
    """Representa el texto redactado como HTML para que Outlook conserve párrafos y saltos."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    reply = html.escape(normalized).replace("\n", "<br>\n")
    quoted = str((quoted_body or {}).get("content") or "")
    if quoted and str((quoted_body or {}).get("contentType") or "").lower() != "html":
        quoted = html.escape(quoted).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>\n")
    return f"<div>{reply}</div><br><br>{signature_html}<br><br>{quoted}"


async def _mail_signature(deps: MailDeps, ctx: ToolContext) -> MailSignature:
    """Resuelve únicamente la ficha del usuario autenticado; no busca ni expone otros empleados."""
    position = phone = None
    if deps.db is not None and ctx.user.auth_method == "entra" and ctx.user.email:
        try:
            async with deps.db.session() as db:
                employee = await db.scalar(
                    select(Employee)
                    .where(func.lower(Employee.email) == ctx.user.email.strip().lower())
                    .order_by(Employee.active.desc(), Employee.sp_id.desc())
                    .limit(1)
                )
            if employee is not None:
                position, phone = employee.position, employee.phone
        except Exception:
            # La firma corporativa no debe bloquear el correo si la ficha HR no está disponible.
            log.warning("mail.signature_profile_lookup_failed")
    return build_mail_signature(ctx.user.display_name, position, phone)


async def _attach_signature_banner(deps: MailDeps, ctx: ToolContext, mailbox: str, draft_id: str) -> None:
    try:
        encoded = base64.b64encode(SIGNATURE_BANNER_PATH.read_bytes()).decode("ascii")
    except OSError as exc:
        raise GraphError("No se encuentra la banda gráfica de la firma corporativa") from exc
    await _graph_request(
        deps,
        ctx,
        "POST",
        f"{mailbox}/messages/{draft_id}/attachments",
        json={
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "sunset-beach-club-banner.png",
            "contentType": "image/png",
            "isInline": True,
            "contentId": SIGNATURE_BANNER_CID,
            "contentBytes": encoded,
        },
    )


def _sender(message: dict[str, Any]) -> str:
    address = (message.get("from") or {}).get("emailAddress") or {}
    return f"{address.get('name') or ''} <{address.get('address') or ''}>".strip()


def _recipients(message: dict[str, Any]) -> str:
    return ", ".join(a for r in message.get("toRecipients", []) if (a := r.get("emailAddress", {}).get("address")))


def _attachment_type_label(name: str | None, content_type: str | None) -> str:
    """Etiqueta breve del tipo de fichero para anunciar («PDF», «Word», «imagen»…), a partir de la
    extensión del nombre (más fiable que el content-type de Graph, que a veces llega genérico)."""
    ext = Path(str(name or "")).suffix.lower().lstrip(".")
    labels = {
        "pdf": "PDF",
        "doc": "Word",
        "docx": "Word",
        "xls": "Excel",
        "xlsx": "Excel",
        "ppt": "PowerPoint",
        "pptx": "PowerPoint",
        "csv": "CSV",
        "txt": "texto",
        "png": "imagen",
        "jpg": "imagen",
        "jpeg": "imagen",
        "gif": "imagen",
        "zip": "comprimido",
    }
    if ext in labels:
        return labels[ext]
    if content_type and "/" in str(content_type):
        return str(content_type).split("/")[-1]
    return "fichero"


def _remember(ctx: ToolContext, messages: list[dict[str, Any]], mailbox: str) -> list[dict[str, Any]]:
    """Referencias cortas (c1, c2…) para que el modelo no tenga que copiar identificadores largos."""
    refs: dict[str, str] = ctx.session_state.setdefault("correos", {})
    mailboxes: dict[str, str] = ctx.session_state.setdefault("correo_mailboxes", {})
    out = []
    for message in messages:
        ref = (
            next((k for k, v in refs.items() if v == message["id"] and mailboxes.get(k) == mailbox), None)
            or f"c{len(refs) + 1}"
        )
        refs[ref] = message["id"]
        mailboxes[ref] = mailbox
        row = {
            "ref": ref,
            "de": _sender(message),
            "asunto": message.get("subject"),
            "recibido": message.get("receivedDateTime") or message.get("sentDateTime"),
            "leido": message.get("isRead"),
            "adjuntos": message.get("hasAttachments"),
            "extracto": (message.get("bodyPreview") or "")[:240],
            "conversacion": message.get("conversationId"),
        }
        if message.get("hasAttachments") and isinstance(message.get("attachments"), list):
            # Solo nombre y tipo (para anunciar el aviso de correo nuevo); el adjunto descargable
            # de verdad, con su URL, se obtiene aparte al abrir el correo (ver leer_correo).
            row["adjuntos_detalle"] = [
                {"nombre": a.get("name"), "tipo": _attachment_type_label(a.get("name"), a.get("contentType"))}
                for a in message["attachments"]
                if a.get("name")
            ]
        if "toRecipients" in message:
            row["para"] = _recipients(message)
        out.append(row)
    return out


def is_noreply(sender: str) -> bool:
    """Remitente automático (no-reply): no admite respuesta."""
    return bool(_NOREPLY.search(sender or ""))


def _mail_rows(items: list[dict[str, Any]], *, sent: bool = False) -> list[dict[str, Any]]:
    """Filas en el formato del panel de correo (2D/3D/holograma/portal), con la referencia para
    poder abrir cada correo. En enviados importa el destinatario (``para``), no el remitente
    (siempre el propio buzón) — nunca se muestra "de" ahí."""
    return [
        {
            "ref": i["ref"],
            "from": i.get("para") if sent else i["de"],
            "subject": i["asunto"],
            "received_at": i["recibido"],
            "has_attachments": bool(i.get("adjuntos")),
            "preview": i.get("extracto"),
            "is_read": bool(i.get("leido")),
            "no_reply": False if sent else is_noreply(i["de"]),
            "conversation_id": i.get("conversacion"),
        }
        for i in items
    ]


def _mail_table(title: str, items: list[dict[str, Any]], *, sent: bool = False) -> dict[str, Any]:
    label, field = ("Para", "para") if sent else ("De", "de")
    view = {
        "type": "table",
        "title": title,
        "columns": ["Ref", label, "Asunto", "Enviado" if sent else "Recibido"],
        "rows": [[i["ref"], i.get(field), i["asunto"], i["recibido"]] for i in items],
    }
    return {**view, "mail_rows": _mail_rows(items, sent=sent)}


def _unavailable(deps: MailDeps, ctx: ToolContext) -> ToolResult | None:
    if deps.graph is None or not deps.settings:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "El buzón de correo no está configurado")
    if not resolve_mailbox(deps.settings.mail, ctx.user) and not ctx.user.graph_assertion:
        reason = (
            "Tu sesión no trae una cuenta de correo (email/UPN): no puedo saber qué buzón abrir."
            if deps.settings.mail.mailbox_source == "user"
            else "El buzón de correo no está configurado"
        )
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, reason)
    return None


def _mailbox_address(deps: MailDeps, ctx: ToolContext, requested: str | None = None, *, ref: str | None = None) -> str:
    """Resuelve buzón personal o compartido; Exchange valida el permiso delegado al consultar Graph."""
    stored = ctx.session_state.get("correo_mailboxes", {}).get(ref) if ref else None
    if requested and requested.strip():
        supplied = requested.strip()
        # No hay un catálogo global de buzones: cada usuario solicita el UPN/dirección
        # del compartido y Graph/Exchange valida sus permisos delegados efectivos.
        mailbox = supplied
        if ctx.user.auth_method != "entra":
            raise GraphError("La selección de buzones compartidos requiere una sesión delegada de Entra")
    else:
        mailbox = (
            stored
            or (ctx.user.user_id if ctx.user.auth_method == "entra" else resolve_mailbox(deps.settings.mail, ctx.user))
            or ""
        )
    if not mailbox:
        raise GraphError("No se pudo resolver el buzón para esta sesión")
    return mailbox


def _mailbox(deps: MailDeps, ctx: ToolContext, requested: str | None = None, *, ref: str | None = None) -> str:
    return GraphClient.user_path(_mailbox_address(deps, ctx, requested, ref=ref))


async def _graph_request(deps: MailDeps, ctx: ToolContext, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    return await deps.graph.request(method, path, user=ctx.user, **kwargs)


# ------------------------------------------------------------------ lectura
class PendientesParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido; vacío = mi buzón. Graph valida el acceso del usuario.",
    )
    limite: int = Field(default=15, ge=1, le=50)
    incluir_texto: bool = Field(default=False, description="true para un triaje a fondo (lee el cuerpo de cada correo)")


def pendientes(deps: MailDeps) -> Tool:
    async def handler(p: PendientesParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        try:
            payload = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon)}/mailFolders/inbox/messages",
                params={
                    "$filter": "isRead eq false",
                    "$top": min(p.limite, 10) if p.incluir_texto else p.limite,
                    "$orderby": "receivedDateTime desc",
                    "$select": f"{SELECT},body" if p.incluir_texto else SELECT,
                },
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido leer el buzón: {exc}")
        messages = payload.get("value", [])
        items = _remember(ctx, messages, _mailbox_address(deps, ctx, p.buzon))
        if p.incluir_texto:
            for item, message in zip(items, messages, strict=True):
                item["texto"] = _plain(message.get("body"))[:1200]
        return ToolResult(
            ToolStatus.OK,
            {"sin_leer_mostrados": len(items), "correos": items},
            _mail_table("Correos sin leer", items),
        )

    return Tool(
        "correos_sin_leer",
        "Correos sin leer del buzón personal, o del compartido que el usuario indique. Úsala SOLO si pide "
        "explícitamente «sin leer», «pendientes de leer» o «no leídos» — para «mis últimos "
        "correos», «resume mi bandeja» o «el correo» sin más (sin mencionar lectura), usa en su "
        "lugar correos_recientes, que no filtra por si están leídos o no. NO es un empleado.",
        PendientesParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


class RecientesParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para usar mi buzón. El acceso se valida en Graph.",
    )
    limite: int = Field(default=15, ge=1, le=50)
    incluir_texto: bool = Field(default=False, description="true para un triaje a fondo (lee el cuerpo de cada correo)")


def recientes(deps: MailDeps) -> Tool:
    async def handler(p: RecientesParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        try:
            payload = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon)}/mailFolders/inbox/messages",
                params={
                    "$top": min(p.limite, 10) if p.incluir_texto else p.limite,
                    "$orderby": "receivedDateTime desc",
                    "$select": f"{SELECT},body" if p.incluir_texto else SELECT,
                    # Nombre/tipo de los adjuntos en la misma llamada (sin descargar contenido):
                    # el aviso de correo nuevo (mail-watch.js) los anuncia explícitamente.
                    "$expand": "attachments($select=name,contentType)",
                },
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido leer el buzón: {exc}")
        messages = payload.get("value", [])
        items = _remember(ctx, messages, _mailbox_address(deps, ctx, p.buzon))
        if p.incluir_texto:
            for item, message in zip(items, messages, strict=True):
                item["texto"] = _plain(message.get("body"))[:1200]
        return ToolResult(
            ToolStatus.OK,
            {"correos_mostrados": len(items), "correos": items},
            _mail_table("Correos recientes", items),
        )

    return Tool(
        "correos_recientes",
        "Los últimos correos recibidos en el buzón indicado (o en el personal si no se indica), SIN filtrar por si están leídos o no — es lo "
        "que se pide con «mis últimos correos», «resume mi bandeja», «correos recibidos» o «el "
        "correo» sin más matización. Si el usuario pide expresamente «sin leer»/«pendientes», usa "
        "correos_sin_leer en su lugar. NO es un empleado.",
        RecientesParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


class EnviadosParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para usar mi buzón. El acceso se valida en Graph.",
    )
    limite: int = Field(default=15, ge=1, le=50)


def enviados(deps: MailDeps) -> Tool:
    async def handler(p: EnviadosParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        try:
            payload = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon)}/mailFolders/sentitems/messages",
                params={
                    "$top": p.limite,
                    "$orderby": "sentDateTime desc",
                    "$select": SELECT_SENT,
                },
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido leer los correos enviados: {exc}")
        items = _remember(ctx, payload.get("value", []), _mailbox_address(deps, ctx, p.buzon))
        return ToolResult(
            ToolStatus.OK,
            {"correos_enviados_mostrados": len(items), "correos": items},
            _mail_table("Correos enviados", items, sent=True),
        )

    return Tool(
        "correos_enviados",
        "Últimos correos ENVIADOS desde el buzón indicado (o el personal) (carpeta Elementos enviados). Úsala cuando el "
        "usuario pregunte por correos que él (o el buzón) ha enviado, no recibido.",
        EnviadosParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


class BuscarParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para usar mi buzón. El acceso se valida en Graph.",
    )
    consulta: str = Field(description="Texto a buscar: remitente, asunto o contenido")
    limite: int = Field(default=15, ge=1, le=50)


def buscar(deps: MailDeps) -> Tool:
    async def handler(p: BuscarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        query = p.consulta.replace('"', " ")
        try:
            payload = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon)}/messages",
                params={"$search": f'"{query}"', "$top": p.limite, "$select": SELECT},
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido buscar en el buzón: {exc}")
        items = _remember(ctx, payload.get("value", []), _mailbox_address(deps, ctx, p.buzon))
        status = ToolStatus.OK if items else ToolStatus.NOT_FOUND
        return ToolResult(
            status,
            {"consulta": p.consulta, "correos": items},
            _mail_table(f"Correos: {p.consulta}", items),
        )

    return Tool(
        "buscar_correos",
        "Busca correos por remitente, asunto o contenido. Usa buzon solo si el usuario identifica un buzón compartido concreto; si dice mis correos, omítelo.",
        BuscarParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


class HiloParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para conservar el buzón de la referencia. Graph valida el acceso.",
    )
    ref: str = Field(description="Referencia (c1, c2…) de cualquier correo de esa conversación")


def hilo(deps: MailDeps) -> Tool:
    async def handler(p: HiloParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        message_id = ctx.session_state.get("correos", {}).get(p.ref)
        if not message_id:
            return ToolResult(ToolStatus.NOT_FOUND, "No conozco esa referencia: lista o busca los correos antes.")
        try:
            # El conversationId puede no estar ya en memoria si el ref viene de una lista antigua.
            message = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon, ref=p.ref)}/messages/{message_id}",
                params={"$select": "conversationId"},
            )
            conversation_id = message.get("conversationId")
            if not conversation_id:
                return ToolResult(ToolStatus.NOT_FOUND, "Ese correo no tiene conversación asociada.")
            payload = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon, ref=p.ref)}/messages",
                params={
                    # Escapado OData estándar: una comilla simple se duplica, nunca se interpola sin más.
                    "$filter": f"conversationId eq '{conversation_id.replace(chr(39), chr(39) * 2)}'",
                    "$orderby": "receivedDateTime asc",
                    "$select": SELECT,
                },
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido leer el hilo: {exc}")
        messages = payload.get("value", [])
        if not messages:
            return ToolResult(ToolStatus.NOT_FOUND, "No se ha encontrado ningún mensaje de esa conversación.")
        items = _remember(ctx, messages, _mailbox_address(deps, ctx, p.buzon, ref=p.ref))
        title = f"Hilo: {items[0]['asunto'] or ''}"
        return ToolResult(
            ToolStatus.OK,
            {"mensajes_en_el_hilo": len(items), "correos": items},
            {**_mail_table(title, items), "type": "mail_thread"},
        )

    return Tool(
        "hilo_correo",
        "Todos los mensajes de la MISMA conversación que un correo concreto (recibidos y "
        "enviados), en orden cronológico — no un mensaje suelto. Úsala con «el hilo completo», "
        "«toda la conversación» o «qué se han dicho sobre esto».",
        HiloParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


def _attachment_text(attachment: dict[str, Any]) -> str | None:
    """Texto extraído de un adjunto de tipo fichero (``#microsoft.graph.fileAttachment``).

    ``None`` si no se puede leer: no es un fichero adjunto (p. ej. un correo reenviado como
    adjunto), supera ``MAX_ATTACHMENT_BYTES``, o el tipo no tiene parser (reutiliza los mismos
    parsers que los adjuntos del chat, ``mia.attachments.parsers`` — nunca una segunda
    implementación de extracción de texto).
    """
    from mia.attachments.intelligence import _parse_sync  # noqa: PLC0415

    content_bytes = attachment.get("contentBytes")
    if not content_bytes or attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
        return None
    if int(attachment.get("size") or 0) > MAX_ATTACHMENT_BYTES:
        return "(adjunto demasiado grande para leer)"
    try:
        raw = base64.b64decode(content_bytes)
        content = _parse_sync(str(attachment.get("contentType") or ""), raw)
    except ValueError:
        return None  # tipo sin parser (p. ej. .zip, .exe): se omite, no es un error
    except Exception as exc:  # adjunto corrupto o mal formado
        log.warning("correo.adjunto_illegible", nombre=attachment.get("name"), error=str(exc)[:200])
        return "(no se ha podido leer este adjunto)"
    return content.full_text[:4000] or None


class LeerParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para conservar el buzón de la referencia. Graph valida el acceso.",
    )
    ref: str = Field(description="Referencia del correo (c1, c2…) de una lista anterior")


async def _attachment_content(
    deps: MailDeps, ctx: ToolContext, mailbox: str, message_id: str, attachment_id: str
) -> dict[str, Any] | None:
    """Representación COMPLETA de un adjunto, incluido ``contentBytes``.

    Microsoft Graph rechaza ``$select=contentBytes`` sobre /attachments (HTTP 400: "Could not
    find a property named 'contentBytes' on type 'microsoft.graph.attachment'") porque esa
    propiedad solo existe en el tipo derivado ``fileAttachment``, no en el tipo base con el que
    OData valida el ``$select`` — ni en la colección ni en un elemento suelto. La única forma
    fiable de obtener el contenido es pedir el adjunto SIN "$select": Graph sirve entonces el tipo
    real ya resuelto, con todas sus propiedades.
    """
    try:
        return await _graph_request(deps, ctx, "GET", f"{mailbox}/messages/{message_id}/attachments/{attachment_id}")
    except GraphError:
        return None


def leer(deps: MailDeps) -> Tool:
    async def handler(p: LeerParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        message_id = ctx.session_state.get("correos", {}).get(p.ref)
        if not message_id:
            return ToolResult(ToolStatus.NOT_FOUND, "No conozco esa referencia: lista o busca los correos antes.")
        mailbox = _mailbox(deps, ctx, p.buzon, ref=p.ref)
        try:
            message = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{mailbox}/messages/{message_id}",
                params={"$select": "subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments"},
            )
            attachments: list[dict[str, Any]] = []
            if message.get("hasAttachments"):
                # "id,name,size,contentType" son propiedades del tipo BASE (attachment): a diferencia
                # de contentBytes, sí admiten $select aquí. Ver _attachment_content().
                attachments = (
                    await _graph_request(
                        deps,
                        ctx,
                        "GET",
                        f"{mailbox}/messages/{message_id}/attachments",
                        params={"$select": "id,name,size,contentType"},
                    )
                ).get("value", [])
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido abrir el correo: {exc}")
        adjuntos = []
        selected_mailbox = _mailbox_address(deps, ctx, p.buzon, ref=p.ref)
        personal_mailbox = resolve_mailbox(deps.settings.mail, ctx.user)
        attachment_url = f"/api/mail/attachment/{message_id}/"
        for a in attachments:
            is_file = a.get("@odata.type") == "#microsoft.graph.fileAttachment"
            contenido = None
            if is_file and int(a.get("size") or 0) > MAX_ATTACHMENT_BYTES:
                contenido = "(adjunto demasiado grande para leer)"
            elif is_file:
                full = await _attachment_content(deps, ctx, mailbox, message_id, str(a.get("id")))
                contenido = _attachment_text(full) if full is not None else "(no se ha podido leer este adjunto)"
            adjuntos.append(
                {
                    "nombre": a.get("name"),
                    "contenido": contenido,
                    "url": (
                        f"{attachment_url}{a.get('id')}"
                        + (
                            f"?buzon={quote(selected_mailbox, safe='@')}"
                            if selected_mailbox not in {personal_mailbox, ctx.user.user_id}
                            else ""
                        )
                        if is_file
                        else None
                    ),
                }
            )
        view = {
            "ref": p.ref,
            "de": _sender(message),
            "para": [r.get("emailAddress", {}).get("address") for r in message.get("toRecipients", [])],
            "asunto": message.get("subject"),
            "recibido": message.get("receivedDateTime"),
            "texto": _plain(message.get("body"))[:8000],
            "adjuntos": adjuntos,
        }
        return ToolResult(ToolStatus.OK, view, {"type": "mail", **view})

    return Tool(
        "leer_correo",
        "Contenido de un correo concreto (por su referencia), incluido el texto de sus adjuntos "
        "(PDF, Word, Excel, CSV, texto) cuando se pueden leer. El parámetro ref debe ser una "
        "referencia cN devuelta por correos_recientes, correos_sin_leer o buscar_correos en esta "
        "misma conversación; nunca uses el remitente, asunto o ID como ref. Si aún no tienes "
        "una referencia, primero lista o busca el correo.",
        LeerParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


# ------------------------------------------------------------------ escritura (COR-001)
class BorradorParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para conservar el buzón de la referencia. Graph valida el acceso.",
    )
    ref: str = Field(description="Referencia del correo al que se responde")
    texto: str = Field(description="Texto de la respuesta", min_length=1, max_length=5000)


def borrador(deps: MailDeps) -> Tool:
    async def handler(p: BorradorParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        if not deps.settings.mail.drafts_enabled:
            return ToolResult(ToolStatus.PERMISSION_DENIED, "La preparación de borradores está desactivada")
        message_id = ctx.session_state.get("correos", {}).get(p.ref)
        if not message_id:
            return ToolResult(ToolStatus.NOT_FOUND, "No conozco esa referencia: lista o busca los correos antes.")
        draft: dict[str, Any] = {}
        signature = await _mail_signature(deps, ctx)
        try:
            mailbox = _mailbox(deps, ctx, p.buzon, ref=p.ref)
            draft = await _graph_request(
                deps, ctx, "POST", f"{mailbox}/messages/{message_id}/createReply", json={"comment": ""}
            )
            quoted_body = draft.get("body")
            if not quoted_body and draft.get("id"):
                current = await _graph_request(
                    deps, ctx, "GET", f"{mailbox}/messages/{draft['id']}", params={"$select": "body"}
                )
                quoted_body = current.get("body")
            await _graph_request(
                deps,
                ctx,
                "PATCH",
                f"{mailbox}/messages/{draft['id']}",
                json={
                    "body": {
                        "contentType": "HTML",
                        "content": _reply_body_html(p.texto, quoted_body, signature.html),
                    }
                },
            )
            await _attach_signature_banner(deps, ctx, mailbox, str(draft["id"]))
        except GraphError as exc:
            if draft.get("id"):
                try:
                    await _graph_request(deps, ctx, "DELETE", f"{mailbox}/messages/{draft['id']}")
                except GraphError:
                    log.warning("mail.reply_draft_cleanup_failed")
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido crear el borrador: {exc}")
        drafts: dict[str, Any] = ctx.session_state.setdefault("borradores", {})
        ref = f"b{len(drafts) + 1}"
        drafts[ref] = {
            "id": draft.get("id"),
            "request_id": ctx.request_id,
            "responde_a": p.ref,
            "mailbox": _mailbox_address(deps, ctx, p.buzon, ref=p.ref),
        }
        mailbox_label = (
            ctx.user.email
            if ctx.user.auth_method == "entra" and drafts[ref]["mailbox"] == ctx.user.user_id and ctx.user.email
            else drafts[ref]["mailbox"]
        )
        drafts[ref]["mailbox_label"] = mailbox_label
        return ToolResult(
            ToolStatus.OK,
            {
                "borrador": ref,
                "responde_a": p.ref,
                "texto": p.texto,
                "mensaje": "Borrador guardado en el buzón. Para enviarlo, el usuario debe confirmarlo.",
            },
            {
                "type": "mail_draft",
                "borrador": ref,
                "texto": p.texto,
                "responde_a": p.ref,
                "envio_habilitado": bool(deps.settings.mail.send_enabled),
                "firma_preview": signature.preview,
                "buzon_envio_nombre": mailbox_label,
            },
        )

    return Tool(
        "preparar_respuesta",
        "Prepara (sin enviar) un borrador de respuesta a un correo. El texto contiene únicamente la respuesta; "
        "la firma corporativa del usuario se añade al guardar.",
        BorradorParams,
        handler,
        permission=Permission.CORREO_ENVIAR,
        audit_resource="correo",
    )


class EnviarParams(BaseModel):
    borrador: str = Field(description="Referencia del borrador (b1, b2…)")


def _send_blocker(deps: MailDeps, draft: dict[str, Any] | None, ctx: ToolContext) -> ToolResult | None:
    """Motivo por el que NO se puede enviar, o None si todo está en regla (COR-001)."""
    denied = ToolStatus.PERMISSION_DENIED
    if not deps.settings.mail.send_enabled:
        return ToolResult(denied, "El envío de correos está desactivado en la configuración")
    if not draft:
        return ToolResult(ToolStatus.NOT_FOUND, "No existe ese borrador en esta conversación.")
    if draft.get("request_id") == ctx.request_id:
        return ToolResult(denied, "El borrador se acaba de preparar: enséñaselo al usuario y espera su confirmación.")
    if not _CONFIRM.search(ctx.user_message) or _DENY.search(ctx.user_message):
        return ToolResult(denied, "Falta la confirmación expresa del usuario para enviar. Pregúntale.")
    if draft.get("enviado"):
        return ToolResult(denied, "Ese borrador ya se envió.")
    if draft.get("mailbox") and draft["mailbox"] not in {
        resolve_mailbox(deps.settings.mail, ctx.user),
        ctx.user.user_id,
        *ctx.session_state.get("correo_mailboxes", {}).values(),
    }:
        return ToolResult(denied, "Ese borrador pertenece a otro buzón: no se puede enviar desde esta sesión.")
    return None


def enviar(deps: MailDeps) -> Tool:
    async def handler(p: EnviarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        draft = ctx.session_state.get("borradores", {}).get(p.borrador)
        if blocker := _send_blocker(deps, draft, ctx):
            return blocker
        assert draft is not None  # noqa: S101
        mailbox = draft.get("mailbox") or resolve_mailbox(deps.settings.mail, ctx.user) or ""
        mailbox_path = GraphClient.user_path(mailbox)
        try:
            message = await _graph_request(
                deps, ctx, "GET", f"{mailbox_path}/messages/{draft['id']}", params={"$select": "toRecipients"}
            )
            to = [r.get("emailAddress", {}).get("address", "") for r in message.get("toRecipients", [])]
            if any(_NOREPLY.search(a) for a in to):
                return ToolResult(
                    ToolStatus.PERMISSION_DENIED,
                    "El destinatario es una dirección que no admite respuestas (no-reply): no se envía.",
                )
            await _graph_request(deps, ctx, "POST", f"{mailbox_path}/messages/{draft['id']}/send")
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido enviar el correo: {exc}")
        draft["enviado"] = True
        return ToolResult(ToolStatus.OK, {"enviado": True, "borrador": p.borrador})

    return Tool(
        "enviar_borrador",
        "Envía un borrador ya revisado, SOLO si el usuario acaba de confirmarlo.",
        EnviarParams,
        handler,
        permission=Permission.CORREO_ENVIAR,
        audit_resource="correo",
    )


class ModificarParams(BaseModel):
    borrador: str = Field(description="Referencia del borrador (b1, b2…)")
    texto: str = Field(description="Nuevo texto de la respuesta", min_length=1, max_length=5000)


def modificar(deps: MailDeps) -> Tool:
    async def handler(p: ModificarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        draft = ctx.session_state.get("borradores", {}).get(p.borrador)
        if not draft or draft.get("enviado"):
            return ToolResult(ToolStatus.NOT_FOUND, "No hay ese borrador pendiente en esta conversación.")
        mailbox = draft.get("mailbox") or resolve_mailbox(deps.settings.mail, ctx.user) or ""
        signature = await _mail_signature(deps, ctx)
        try:
            await _graph_request(
                deps,
                ctx,
                "PATCH",
                f"{GraphClient.user_path(mailbox)}/messages/{draft['id']}",
                json={
                    "body": {
                        "contentType": "HTML",
                        "content": _reply_body_html(p.texto, signature_html=signature.html),
                    }
                },
            )
            attachments = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{GraphClient.user_path(mailbox)}/messages/{draft['id']}/attachments",
                params={"$select": "id,contentId"},
            )
            if not any(a.get("contentId") == SIGNATURE_BANNER_CID for a in attachments.get("value", [])):
                await _attach_signature_banner(deps, ctx, GraphClient.user_path(mailbox), str(draft["id"]))
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido modificar el borrador: {exc}")
        draft["request_id"] = ctx.request_id  # cambiado: hay que volver a enseñarlo antes de enviar
        return ToolResult(
            ToolStatus.OK,
            {
                "borrador": p.borrador,
                "texto": p.texto,
                "mensaje": "Borrador actualizado; enséñalo y espera confirmación.",
            },
            {
                "type": "mail_draft",
                "borrador": p.borrador,
                "texto": p.texto,
                "envio_habilitado": bool(deps.settings.mail.send_enabled),
                "firma_preview": signature.preview,
                "buzon_envio_nombre": draft.get("mailbox_label")
                or (
                    ctx.user.email
                    if ctx.user.auth_method == "entra" and draft.get("mailbox") == ctx.user.user_id
                    else draft.get("mailbox")
                ),
            },
        )

    return Tool(
        "modificar_borrador",
        "Cambia el texto de un borrador preparado (antes de enviarlo).",
        ModificarParams,
        handler,
        permission=Permission.CORREO_ENVIAR,
        audit_resource="correo",
    )


class DescartarParams(BaseModel):
    borrador: str


def descartar(deps: MailDeps) -> Tool:
    async def handler(p: DescartarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        drafts = ctx.session_state.get("borradores", {})
        draft = drafts.get(p.borrador)
        if not draft or draft.get("enviado"):
            return ToolResult(ToolStatus.NOT_FOUND, "No hay ese borrador pendiente en esta conversación.")
        mailbox = draft.get("mailbox") or resolve_mailbox(deps.settings.mail, ctx.user) or ""
        try:
            await _graph_request(deps, ctx, "DELETE", f"{GraphClient.user_path(mailbox)}/messages/{draft['id']}")
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido descartar el borrador: {exc}")
        drafts.pop(p.borrador, None)
        return ToolResult(ToolStatus.OK, {"descartado": p.borrador})

    return Tool(
        "descartar_borrador",
        "Elimina un borrador preparado que ya no se quiere enviar.",
        DescartarParams,
        handler,
        permission=Permission.CORREO_ENVIAR,
        audit_resource="correo",
    )


class GuardadosParams(BaseModel):
    buzon: str | None = Field(
        default=None,
        description="UPN o dirección del buzón compartido solicitado; omítelo para usar mi buzón. El acceso se valida en Graph.",
    )
    limite: int = Field(default=10, ge=1, le=30)


def guardados(deps: MailDeps) -> Tool:
    async def handler(p: GuardadosParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps, ctx):
            return problem
        try:
            payload = await _graph_request(
                deps,
                ctx,
                "GET",
                f"{_mailbox(deps, ctx, p.buzon)}/mailFolders/drafts/messages",
                params={"$top": p.limite, "$orderby": "lastModifiedDateTime desc", "$select": SELECT},
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido leer los borradores: {exc}")
        items = _remember(ctx, payload.get("value", []), _mailbox_address(deps, ctx, p.buzon))
        return ToolResult(ToolStatus.OK, {"borradores_en_el_buzon": items})

    return Tool(
        "borradores_guardados",
        "Borradores guardados en el buzón propio.",
        GuardadosParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


def register(registry: ToolRegistry, deps: MailDeps) -> None:
    for factory in (
        pendientes,
        recientes,
        enviados,
        buscar,
        hilo,
        leer,
        borrador,
        enviar,
        modificar,
        descartar,
        guardados,
    ):
        registry.register(factory(deps))
