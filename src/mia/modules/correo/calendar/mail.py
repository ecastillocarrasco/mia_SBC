"""Coordinación con las herramientas de correo existentes, sin reintentar envíos."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

from mia.auth import Permission
from mia.conversation import ToolContext, ToolResult, ToolStatus
from mia.modules.correo.calendar.models import CalendarError, CalendarPerson
from mia.modules.correo.calendar.service import digest
from mia.modules.correo.deps import MailDeps
from mia.modules.correo.tools import BorradorParams, EnviarParams, _send_blocker, borrador, enviar


class SingleAttemptGraph:
    """Conserva herramientas y validaciones de correo, restringiendo sus reintentos."""

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self.graph.request(method, path, retry_safe=method == "GET", **kwargs))


def safe_deps(deps: MailDeps) -> MailDeps:
    return MailDeps(settings=deps.settings, db=deps.db, graph=SingleAttemptGraph(deps.graph))


async def source_people(deps: MailDeps, ctx: ToolContext, ref: str) -> list[CalendarPerson]:
    ctx.user.require(Permission.CORREO_LEER)
    from mia.modules.correo.tools import _mailbox  # noqa: PLC0415

    message_id = ctx.session_state.get("correos", {}).get(ref)
    if not message_id:
        raise CalendarError("Lista o lee el correo antes de crear una reunión relacionada")
    message = await deps.graph.request(
        "GET",
        f"{_mailbox(deps, ctx, ref=ref)}/messages/{quote(message_id, safe='')}",
        user=ctx.user,
        params={"$select": "id,from,toRecipients,subject,bodyPreview,conversationId"},
    )
    # Source identity comes from the authenticated mailbox, never from an invented address.
    values = [message.get("from") or {}, *message.get("toRecipients", [])]
    people = []
    for value in values:
        address = value.get("emailAddress") or {}
        if address.get("address"):
            people.append(CalendarPerson(address=address["address"], name=address.get("name", "")))
    return people


async def _draft_snapshot(deps: MailDeps, ctx: ToolContext, draft: dict[str, Any]) -> str:
    from mia.connectors.graph import GraphClient  # noqa: PLC0415

    current = await deps.graph.request(
        "GET",
        f"{GraphClient.user_path(draft['mailbox'])}/messages/{quote(draft['id'], safe='')}",
        user=ctx.user,
        params={"$select": "subject,body,toRecipients,ccRecipients,bccRecipients,changeKey,isDraft"},
    )
    if current.get("isDraft") is not True:
        raise CalendarError("El mensaje ya no es un borrador")
    return digest(current)


async def prepare_reply(deps: MailDeps, ctx: ToolContext, ref: str, text: str) -> dict[str, Any] | ToolResult:
    ctx.user.require(Permission.CORREO_ENVIAR)
    if not deps.settings.mail.send_enabled:
        return ToolResult(
            ToolStatus.PERMISSION_DENIED, "El envío está desactivado; no se prepara una acción compuesta de envío."
        )
    result = await borrador(safe_deps(deps)).handler(BorradorParams(ref=ref, texto=text), ctx)
    if result.status != ToolStatus.OK:
        return result
    draft_ref = result.summary["borrador"]
    draft = ctx.session_state["borradores"][draft_ref]
    return {"mail_draft": draft_ref, "mail_text": text, "mail_snapshot": await _draft_snapshot(deps, ctx, draft)}


async def validate_reply(deps: MailDeps, ctx: ToolContext, operation: dict[str, Any]) -> None:
    draft = ctx.session_state.get("borradores", {}).get(operation["mail_draft"])
    blocker = _send_blocker(deps, draft, ctx)
    if blocker:
        raise CalendarError(str(blocker.summary))
    if await _draft_snapshot(deps, ctx, draft) != operation["mail_snapshot"]:
        raise CalendarError("El borrador cambió; prepara y confirma una propuesta nueva")


async def send_reply(deps: MailDeps, ctx: ToolContext, operation: dict[str, Any]) -> str:
    from mia.connectors.graph import GraphError  # noqa: PLC0415

    try:
        await validate_reply(deps, ctx, operation)
        result = await enviar(safe_deps(deps)).handler(EnviarParams(borrador=operation["mail_draft"]), ctx)
        return "sent" if result.status == ToolStatus.OK else "failed_or_unknown_do_not_retry"
    except (CalendarError, GraphError):
        return "failed_or_unknown_do_not_retry"
