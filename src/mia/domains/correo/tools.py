"""Correo del buzón compartido de RRHH (Microsoft Graph).

COR-001: mIA puede leer, buscar y preparar borradores. Enviar exige que el
borrador se haya preparado en un turno anterior (el usuario lo ha visto) y que el
mensaje actual del usuario lo confirme expresamente. Además, el envío está
desactivado salvo que se habilite en la configuración.
"""

from __future__ import annotations

import html
import re
from typing import Any

from pydantic import BaseModel, Field

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.domains.common import Deps, table
from mia.sources.graph import GraphClient, GraphError

_TAGS = re.compile(r"<[^>]+>")
_CONFIRM = re.compile(r"\b(s[ií]|env[ií]a(lo)?|adelante|confirm[oa]|de acuerdo|vale|ok)\b", re.IGNORECASE)
_NOREPLY = re.compile(r"no-?reply|do-?not-?reply|noresponder", re.IGNORECASE)
_DENY = re.compile(r"\b(no|espera|todav[ií]a no|cancela)\b", re.IGNORECASE)
SELECT = "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,isRead"


def _plain(body: dict[str, Any] | None) -> str:
    content = str((body or {}).get("content") or "")
    if (body or {}).get("contentType", "").lower() == "html":
        content = html.unescape(_TAGS.sub(" ", content))
    return " ".join(content.split())


def _sender(message: dict[str, Any]) -> str:
    address = (message.get("from") or {}).get("emailAddress") or {}
    return f"{address.get('name') or ''} <{address.get('address') or ''}>".strip()


def _remember(ctx: ToolContext, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Referencias cortas (c1, c2…) para que el modelo no tenga que copiar identificadores largos."""
    refs: dict[str, str] = ctx.session_state.setdefault("correos", {})
    out = []
    for message in messages:
        ref = next((k for k, v in refs.items() if v == message["id"]), None) or f"c{len(refs) + 1}"
        refs[ref] = message["id"]
        out.append(
            {
                "ref": ref,
                "de": _sender(message),
                "asunto": message.get("subject"),
                "recibido": message.get("receivedDateTime"),
                "leido": message.get("isRead"),
                "adjuntos": message.get("hasAttachments"),
                "extracto": (message.get("bodyPreview") or "")[:240],
            }
        )
    return out


def _unavailable(deps: Deps) -> ToolResult | None:
    if deps.graph is None or not deps.settings or not deps.settings.mail.mailbox:
        return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "El buzón de correo no está configurado")
    return None


def _mailbox(deps: Deps) -> str:
    return GraphClient.user_path(deps.settings.mail.mailbox)


# ------------------------------------------------------------------ lectura
class PendientesParams(BaseModel):
    limite: int = Field(default=15, ge=1, le=50)
    incluir_texto: bool = Field(default=False, description="true para un triaje a fondo (lee el cuerpo de cada correo)")


def pendientes(deps: Deps) -> Tool:
    async def handler(p: PendientesParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        try:
            payload = await deps.graph.request(
                "GET",
                f"{_mailbox(deps)}/mailFolders/inbox/messages",
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
        items = _remember(ctx, messages)
        if p.incluir_texto:
            for item, message in zip(items, messages, strict=True):
                item["texto"] = _plain(message.get("body"))[:1200]
        return ToolResult(
            ToolStatus.OK,
            {"sin_leer_mostrados": len(items), "correos": items},
            table(
                "Correos sin leer",
                ["Ref", "De", "Asunto", "Recibido"],
                [[i["ref"], i["de"], i["asunto"], i["recibido"]] for i in items],
            ),
        )

    return Tool(
        "correos_sin_leer",
        "Correos sin leer del buzón de RRHH (los más recientes).",
        PendientesParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


class BuscarParams(BaseModel):
    consulta: str = Field(description="Texto a buscar: remitente, asunto o contenido")
    limite: int = Field(default=15, ge=1, le=50)


def buscar(deps: Deps) -> Tool:
    async def handler(p: BuscarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        query = p.consulta.replace('"', " ")
        try:
            payload = await deps.graph.request(
                "GET",
                f"{_mailbox(deps)}/messages",
                params={"$search": f'"{query}"', "$top": p.limite, "$select": SELECT},
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido buscar en el buzón: {exc}")
        items = _remember(ctx, payload.get("value", []))
        status = ToolStatus.OK if items else ToolStatus.NOT_FOUND
        return ToolResult(
            status,
            {"consulta": p.consulta, "correos": items},
            table(
                f"Correos: {p.consulta}",
                ["Ref", "De", "Asunto", "Recibido"],
                [[i["ref"], i["de"], i["asunto"], i["recibido"]] for i in items],
            ),
        )

    return Tool(
        "buscar_correos",
        "Busca correos en el buzón de RRHH por remitente, asunto o contenido.",
        BuscarParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


class LeerParams(BaseModel):
    ref: str = Field(description="Referencia del correo (c1, c2…) de una lista anterior")


def leer(deps: Deps) -> Tool:
    async def handler(p: LeerParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        message_id = ctx.session_state.get("correos", {}).get(p.ref)
        if not message_id:
            return ToolResult(ToolStatus.NOT_FOUND, "No conozco esa referencia: lista o busca los correos antes.")
        try:
            message = await deps.graph.request(
                "GET",
                f"{_mailbox(deps)}/messages/{message_id}",
                params={"$select": "subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments"},
            )
            attachments: list[dict[str, Any]] = []
            if message.get("hasAttachments"):
                attachments = (
                    await deps.graph.request(
                        "GET",
                        f"{_mailbox(deps)}/messages/{message_id}/attachments",
                        params={"$select": "name,size"},
                    )
                ).get("value", [])
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido abrir el correo: {exc}")
        view = {
            "ref": p.ref,
            "de": _sender(message),
            "para": [r.get("emailAddress", {}).get("address") for r in message.get("toRecipients", [])],
            "asunto": message.get("subject"),
            "recibido": message.get("receivedDateTime"),
            "texto": _plain(message.get("body"))[:4000],
            "adjuntos": [a.get("name") for a in attachments],
        }
        return ToolResult(ToolStatus.OK, view, {"type": "mail", **view})

    return Tool(
        "leer_correo",
        "Contenido de un correo concreto (por su referencia).",
        LeerParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


# ------------------------------------------------------------------ escritura (COR-001)
class BorradorParams(BaseModel):
    ref: str = Field(description="Referencia del correo al que se responde")
    texto: str = Field(description="Texto de la respuesta", min_length=1, max_length=5000)


def borrador(deps: Deps) -> Tool:
    async def handler(p: BorradorParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        if not deps.settings.mail.drafts_enabled:
            return ToolResult(ToolStatus.PERMISSION_DENIED, "La preparación de borradores está desactivada")
        message_id = ctx.session_state.get("correos", {}).get(p.ref)
        if not message_id:
            return ToolResult(ToolStatus.NOT_FOUND, "No conozco esa referencia: lista o busca los correos antes.")
        try:
            draft = await deps.graph.request(
                "POST", f"{_mailbox(deps)}/messages/{message_id}/createReply", json={"comment": p.texto}
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido crear el borrador: {exc}")
        drafts: dict[str, Any] = ctx.session_state.setdefault("borradores", {})
        ref = f"b{len(drafts) + 1}"
        drafts[ref] = {"id": draft.get("id"), "request_id": ctx.request_id, "responde_a": p.ref}
        return ToolResult(
            ToolStatus.OK,
            {
                "borrador": ref,
                "responde_a": p.ref,
                "texto": p.texto,
                "mensaje": "Borrador guardado en el buzón. Para enviarlo, el usuario debe confirmarlo.",
            },
            {"type": "mail_draft", "borrador": ref, "texto": p.texto},
        )

    return Tool(
        "preparar_respuesta",
        "Prepara (sin enviar) un borrador de respuesta a un correo.",
        BorradorParams,
        handler,
        permission=Permission.CORREO_ENVIAR,
        audit_resource="correo",
    )


class EnviarParams(BaseModel):
    borrador: str = Field(description="Referencia del borrador (b1, b2…)")


def _send_blocker(deps: Deps, draft: dict[str, Any] | None, ctx: ToolContext) -> ToolResult | None:
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
    return None


def enviar(deps: Deps) -> Tool:
    async def handler(p: EnviarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        draft = ctx.session_state.get("borradores", {}).get(p.borrador)
        if blocker := _send_blocker(deps, draft, ctx):
            return blocker
        assert draft is not None  # noqa: S101
        try:
            message = await deps.graph.request(
                "GET", f"{_mailbox(deps)}/messages/{draft['id']}", params={"$select": "toRecipients"}
            )
            to = [r.get("emailAddress", {}).get("address", "") for r in message.get("toRecipients", [])]
            if any(_NOREPLY.search(a) for a in to):
                return ToolResult(
                    ToolStatus.PERMISSION_DENIED,
                    "El destinatario es una dirección que no admite respuestas (no-reply): no se envía.",
                )
            await deps.graph.request("POST", f"{_mailbox(deps)}/messages/{draft['id']}/send")
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


def modificar(deps: Deps) -> Tool:
    async def handler(p: ModificarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        draft = ctx.session_state.get("borradores", {}).get(p.borrador)
        if not draft or draft.get("enviado"):
            return ToolResult(ToolStatus.NOT_FOUND, "No hay ese borrador pendiente en esta conversación.")
        try:
            await deps.graph.request(
                "PATCH",
                f"{_mailbox(deps)}/messages/{draft['id']}",
                json={"body": {"contentType": "Text", "content": p.texto}},
            )
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
            {"type": "mail_draft", "borrador": p.borrador, "texto": p.texto},
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


def descartar(deps: Deps) -> Tool:
    async def handler(p: DescartarParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        drafts = ctx.session_state.get("borradores", {})
        draft = drafts.get(p.borrador)
        if not draft or draft.get("enviado"):
            return ToolResult(ToolStatus.NOT_FOUND, "No hay ese borrador pendiente en esta conversación.")
        try:
            await deps.graph.request("DELETE", f"{_mailbox(deps)}/messages/{draft['id']}")
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
    limite: int = Field(default=10, ge=1, le=30)


def guardados(deps: Deps) -> Tool:
    async def handler(p: GuardadosParams, ctx: ToolContext) -> ToolResult:
        if problem := _unavailable(deps):
            return problem
        try:
            payload = await deps.graph.request(
                "GET",
                f"{_mailbox(deps)}/mailFolders/drafts/messages",
                params={"$top": p.limite, "$orderby": "lastModifiedDateTime desc", "$select": SELECT},
            )
        except GraphError as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, f"No he podido leer los borradores: {exc}")
        items = _remember(ctx, payload.get("value", []))
        return ToolResult(ToolStatus.OK, {"borradores_en_el_buzon": items})

    return Tool(
        "borradores_guardados",
        "Borradores guardados en el buzón de RRHH.",
        GuardadosParams,
        handler,
        permission=Permission.CORREO_LEER,
        audit_resource="correo",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (pendientes, buscar, leer, borrador, enviar, modificar, descartar, guardados):
        registry.register(factory(deps))
