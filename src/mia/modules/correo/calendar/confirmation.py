"""Confirmación humana vinculada a propuestas persistidas del usuario y conversación."""

import re
from dataclasses import dataclass

from mia.conversation import ToolContext, ToolResult, ToolStatus
from mia.data.calendar import CalendarOperation
from mia.modules.correo.calendar.presentation import describe_operation
from mia.modules.correo.calendar.store import OperationStore
from mia.text import normalize_key

_NATURAL = frozenset(
    {
        "si",
        "si confirmo",
        "confirmo",
        "adelante",
        "si adelante",
        "si confirmo el cambio",
        "confirmo el cambio",
        "confirma el cambio",
        "confirmo la propuesta",
        "confirma la propuesta",
    }
)
_EXPLICIT = re.compile(r"(?:si )?(?:confirmo|confirma)(?: la propuesta| el)? (cambio ?\d+|[a-f0-9]{32})")


def reference(ctx: ToolContext, operation_id: str) -> str:
    refs = ctx.session_state.setdefault("calendar_proposal_refs", {})
    existing = next((name for name, identifier in refs.items() if identifier == operation_id), None)
    label = existing or f"cambio {len(refs) + 1}"
    refs[label] = operation_id
    return str(label)


def _identifier(ctx: ToolContext, value: str) -> str | None:
    value = normalize_key(value)
    if re.fullmatch(r"[a-f0-9]{32}", value):
        return value
    value = re.sub(r"^cambio\s*(\d+)$", r"cambio \1", value)
    identifier = ctx.session_state.get("calendar_proposal_refs", {}).get(value)
    return identifier if isinstance(identifier, str) else None


@dataclass(frozen=True)
class Selection:
    record: CalendarOperation
    implicit: bool


async def resolve(store: OperationStore, ctx: ToolContext, requested: str | None) -> Selection | ToolResult:  # noqa: PLR0911
    message = normalize_key(ctx.user_message)
    explicit = _EXPLICIT.fullmatch(message)
    requested_id = _identifier(ctx, requested) if requested else None
    if requested and not requested_id:
        return ToolResult(ToolStatus.NOT_FOUND, "No conozco esa referencia de cambio en esta conversación.")
    if explicit:
        chosen = _identifier(ctx, explicit[1])
        if not chosen or (requested_id and requested_id != chosen):
            return ToolResult(ToolStatus.PERMISSION_DENIED, "La confirmación no corresponde al cambio seleccionado.")
    elif message in _NATURAL:
        pending = await store.pending(ctx)
        if len(pending) > 1:
            return ToolResult(
                ToolStatus.AMBIGUOUS,
                {
                    "mensaje": "Hay varios cambios pendientes. Indica cuál confirmas, por ejemplo: confirma cambio 1.",
                    "cambios": [
                        {"referencia": reference(ctx, item.id), **describe_operation(item.payload)} for item in pending
                    ],
                },
            )
        chosen = pending[0].id if pending else requested_id or ctx.session_state.get("calendar_last_proposal")
        if requested_id and chosen != requested_id:
            return ToolResult(ToolStatus.PERMISSION_DENIED, "El cambio seleccionado no es la propuesta pendiente.")
    else:
        return ToolResult(ToolStatus.PERMISSION_DENIED, "Revisa el cambio y responde «sí, confirmo» o «adelante».")
    record = await store.get(ctx, chosen) if chosen else None
    if record is None:
        return ToolResult(ToolStatus.NOT_FOUND, "No hay una propuesta disponible para este usuario y conversación.")
    return Selection(record, implicit=explicit is None)
