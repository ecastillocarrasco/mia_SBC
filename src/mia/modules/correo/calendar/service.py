"""Reglas de agenda y propuestas, independientes de Microsoft."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from mia.auth import Permission
from mia.connectors.graph import GraphError, GraphMutationUncertain
from mia.conversation import ToolContext, ToolResult, ToolStatus
from mia.modules.correo.calendar.agenda import local_datetime
from mia.modules.correo.calendar.confirmation import reference, resolve
from mia.modules.correo.calendar.models import CalendarError, CalendarEvent, CalendarPerson, CalendarProvider
from mia.modules.correo.calendar.presentation import describe_operation
from mia.modules.correo.calendar.store import OperationStore
from mia.modules.correo.deps import MailDeps
from mia.modules.rrhh.common import PersonaParams, person_problem, resolve_person

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(event: CalendarEvent) -> str:
    return digest(event.model_dump(mode="json"))


def timezone_for(deps: MailDeps, ctx: ToolContext) -> str:
    timezone = deps.settings.mail.calendar.user_timezones.get(ctx.user.user_id) or deps.settings.timezone
    ZoneInfo(timezone)
    return str(timezone)


def valid_times(start: datetime, end: datetime, timezone: str, all_day: bool = False) -> tuple[datetime, datetime]:
    start = local_datetime(start, timezone)
    end = local_datetime(end, timezone)
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise CalendarError("El final debe ser posterior al inicio")
    if all_day and (start.time().isoformat() != "00:00:00" or end.time().isoformat() != "00:00:00"):
        raise CalendarError("Un evento de día completo empieza y termina a medianoche; el final es exclusivo")
    return start, end


async def resolve_attendees(
    deps: MailDeps,
    ctx: ToolContext,
    values: list[str],
    known: list[CalendarPerson] | None = None,
) -> list[CalendarPerson] | ToolResult:
    verified = ctx.session_state.setdefault("calendar_contacts", {})
    for person in known or []:
        verified[person.address.lower()] = person.model_dump()
    people = []
    explicit = {match.group().lower() for match in EMAIL.finditer(ctx.user_message)}
    for value in values:
        address = value.strip().lower()
        if EMAIL.fullmatch(address):
            if address not in explicit and address not in verified:
                return ToolResult(
                    ToolStatus.AMBIGUOUS, "Confirma la dirección del asistente; no consta en una fuente autorizada."
                )
            people.append(CalendarPerson.model_validate(verified.get(address, {"address": address})))
            continue
        if not ctx.user.has(Permission.EMPLEADOS_LEER):
            return ToolResult(
                ToolStatus.PERMISSION_DENIED,
                "No puedes consultar el directorio de empleados. Indica el email del asistente.",
            )
        async with deps.db.session() as session:
            match = await resolve_person(session, PersonaParams(nombre=value), ctx=ctx)
        if match.employee is None:
            return person_problem(match, value)
        if not match.employee.email or not EMAIL.fullmatch(match.employee.email):
            return ToolResult(ToolStatus.NOT_FOUND, "La persona no tiene una dirección de correo válida registrada.")
        person = CalendarPerson(address=match.employee.email, name=match.employee.name)
        verified[person.address.lower()] = person.model_dump()
        people.append(person)
    return list({person.address.lower(): person for person in people}.values())


class CalendarService:
    def __init__(self, deps: MailDeps, provider: CalendarProvider) -> None:
        self.deps = deps
        self.provider = provider
        self.store = OperationStore(deps.db)

    async def proposal(self, ctx: ToolContext, operation: dict[str, Any]) -> ToolResult:
        operation["provider"] = self.provider.name
        operation["payload_digest"] = digest(operation)
        proposed = await self.store.propose(ctx, operation, self.deps.settings.mail.calendar.proposal_ttl_seconds)
        label = reference(ctx, proposed.id)
        ctx.session_state["calendar_last_proposal"] = proposed.id
        pending = await self.store.pending(ctx)
        # The button submits a normal chat turn; server-side confirmation remains authoritative.
        review = {k: v for k, v in operation.items() if k not in {"snapshot", "payload_digest", "mail_snapshot"}}
        return ToolResult.ok(
            {
                "propuesta": proposed.id,
                "referencia": label,
                "resumen": describe_operation(operation),
                "operacion": review,
                "caduca": proposed.expires_at.isoformat(),
                "ejecutado": False,
                "confirmacion_requerida": "Sí, confirmo" if len(pending) == 1 else f"confirma {label}",
                "instruccion": "Muestra todos los parámetros y cualquier comunicación antes de pedir confirmación. "
                "Incluye fecha, hora de inicio y hora de fin, con zona horaria. "
                "El campo propuesta es un identificador interno: no lo muestres ni pidas al usuario que lo copie. "
                "Si hay un único cambio, pide responder «sí, confirmo» o «adelante» en otro turno; "
                "si hay varios, usa referencias legibles como «confirma cambio 1».",
            },
            presentation={
                "type": "calendar", "title": "Cambio de agenda propuesto", "timezone": operation["timezone"],
                "days": [], "events": [],
                "confirmation": {
                    "prompt": f"confirma {label}", "label": "Sí, confirmo", "reference": label,
                    "expires_at": proposed.expires_at.isoformat(),
                    "review": {**describe_operation(operation), "detalle": review},
                },
            },
        )

    async def execute(self, ctx: ToolContext, operation_id: str | None = None) -> ToolResult:  # noqa: PLR0911, PLR0912, PLR0915
        selection = await resolve(self.store, ctx, operation_id)
        if isinstance(selection, ToolResult):
            return selection
        record = selection.record
        operation_id = record.id
        if record.status != "pending":
            return ToolResult.ok(
                {
                    "estado": record.status,
                    "resultado": record.result,
                    "repetido": False,
                    "mensaje": "Esta propuesta no se vuelve a ejecutar.",
                }
            )
        expires = record.expires_at.replace(tzinfo=UTC) if record.expires_at.tzinfo is None else record.expires_at
        if expires <= datetime.now(UTC):
            return ToolResult(ToolStatus.PERMISSION_DENIED, "La propuesta ha caducado; prepara otra.")
        if record.request_id == ctx.request_id:
            return ToolResult(ToolStatus.PERMISSION_DENIED, "Muestra la propuesta y espera un turno posterior.")
        operation = dict(record.payload)
        checksum = operation.pop("payload_digest", "")
        if checksum != digest(operation) or record.provider != self.provider.name:
            return ToolResult(
                ToolStatus.PERMISSION_DENIED, "La propuesta cambió o corresponde a otro proveedor; prepara otra."
            )
        if operation.get("mail_draft") and not ctx.user.has(Permission.CORREO_ENVIAR):
            return ToolResult(ToolStatus.PERMISSION_DENIED, "No tienes permiso para enviar la respuesta de correo.")
        try:
            if operation.get("event_id"):
                current = await self.provider.get_event(
                    ctx.user,
                    operation["event_id"],
                    operation["timezone"],
                    operation["calendar_id"],
                )
                if snapshot(current) != operation["snapshot"]:
                    await self.store.finish(ctx, operation_id, "stale", {"error_type": "EventChanged"})
                    return ToolResult(
                        ToolStatus.PERMISSION_DENIED, "El evento ha cambiado. Prepara y confirma una propuesta nueva."
                    )
                if operation["action"] in {"update", "reschedule", "cancel"} and not current.can_modify:
                    return ToolResult(
                        ToolStatus.PERMISSION_DENIED, "Solo el organizador puede modificar o cancelar la reunión."
                    )
            if operation.get("mail_draft"):
                from mia.modules.correo.calendar.mail import validate_reply  # noqa: PLC0415

                await validate_reply(self.deps, ctx, operation)
            if not await self.store.claim(ctx, operation_id, require_unique=selection.implicit):
                return ToolResult(
                    ToolStatus.PERMISSION_DENIED, "Propuesta caducada o ya en ejecución; no se ha repetido."
                )
        except (GraphError, CalendarError) as exc:
            return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, str(exc))

        result: dict[str, Any] = {}
        try:
            result = await self.provider.mutate(ctx.user, operation, operation_id)
            # Persist immediately after the external write, before verification or another side effect.
            await self.store.finish(ctx, operation_id, "applied", result)
        except GraphMutationUncertain:
            await self.store.finish(ctx, operation_id, "unknown", {"error_type": "GraphMutationUncertain"})
            return ToolResult(
                ToolStatus.SOURCE_UNAVAILABLE,
                "Resultado desconocido. No se repetirá; comprueba el calendario antes de crear otra propuesta.",
            )
        except (GraphError, CalendarError) as exc:
            await self.store.finish(ctx, operation_id, "failed", {"error_type": type(exc).__name__})
            return ToolResult(
                ToolStatus.SOURCE_UNAVAILABLE, "El proveedor rechazó la operación; no se reintentará automáticamente."
            )
        except Exception as exc:
            await self.store.finish(ctx, operation_id, "unknown", {"error_type": type(exc).__name__})
            return ToolResult(
                ToolStatus.SOURCE_UNAVAILABLE,
                "No se pudo confirmar la escritura. No se repetirá; comprueba el calendario.",
            )

        result["verified"] = False
        if operation["action"] == "propose_time":
            result["verification_pending"] = True
            result["message"] = "Graph aceptó la propuesta; no se ha verificado su entrega al organizador."
        elif operation["action"] in {"create", "update", "reschedule", "accept", "tentative"}:
            try:
                if result.get("event_id"):
                    event = await self.provider.get_event(
                        ctx.user,
                        result["event_id"],
                        operation["timezone"],
                        operation["calendar_id"],
                    )
                    result["verified"] = self._matches(operation, event)
                    result["event"] = event.model_dump(mode="json")
            except (GraphError, CalendarError):
                result["verification_pending"] = True
        else:
            try:
                event = await self.provider.get_event(
                    ctx.user,
                    result["event_id"],
                    operation["timezone"],
                    operation["calendar_id"],
                )
                result["verified"] = (
                    event.status == "cancelled" if operation["action"] == "cancel" else event.response == "declined"
                )
            except GraphError as exc:
                result["verified"] = exc.status_code == 404
            except CalendarError:
                pass
            result["verification_pending"] = not result["verified"]
        if operation.get("mail_draft"):
            from mia.modules.correo.calendar.mail import send_reply  # noqa: PLC0415

            if not result["verified"]:
                result["mail"] = "not_sent_calendar_verification_pending"
            else:
                result["mail"] = await send_reply(self.deps, ctx, operation)
        status = "completed" if result["verified"] and result.get("mail", "sent") == "sent" else "partial"
        await self.store.finish(ctx, operation_id, status, result)
        return ToolResult.ok({"estado": status, "resultado": result, "repetir": False})

    @staticmethod
    def _matches(operation: dict[str, Any], event: CalendarEvent) -> bool:  # noqa: PLR0911
        action = operation["action"]
        if action in {"accept", "tentative", "propose_time"}:
            return event.response == ("accepted" if action == "accept" else "tentativelyAccepted")
        changes = operation.get("changes", {})
        for field in ("subject", "location", "all_day"):
            if field in changes and getattr(event, field) != changes[field]:
                return False
        for field in ("start", "end"):
            if field in changes and getattr(event, field) != datetime.fromisoformat(changes[field]):
                return False
        if "attendees" in changes:
            expected = {a["address"].lower() for a in changes["attendees"]}
            if expected != {a.address.lower() for a in event.attendees}:
                return False
        if "description" in changes and changes["description"] not in event.description:
            return False
        if "recurrence" in changes:
            if not event.recurrence:
                return False
            expected_recurrence = changes["recurrence"]
            if any(event.recurrence.get(key) != value for key, value in expected_recurrence.items()):
                return False
        return not (changes.get("online") and not event.online_url)
