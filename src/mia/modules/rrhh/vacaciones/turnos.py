"""Same-person, same-day vacation/working-shift conflicts across the complete requested period."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import func, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, ShiftDay, Vacation
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import (
    ActivosParams,
    Deps,
    Periodo,
    confirmed_vacations,
    department_problem,
    population_state,
    resolve_department,
    table,
)
from mia.query.week import requested_week
from mia.text import normalize_key


class CruceVacacionesTurnosParams(Periodo, ActivosParams):
    departamento: str | None = None


def _verifies_request(message: str) -> bool:
    text = normalize_key(message)
    return bool(
        re.search(r"\bvacaciones\b", text)
        and re.search(r"\bturnos?\b", text)
        and re.search(r"\b(?:cruz\w*|conflict\w*|incompatib\w*)\b", text)
    )


def _compare(
    people: list[Employee], shifts: list[ShiftDay], vacations: list[Vacation]
) -> tuple[list[list[Any]], set[int], int]:
    by_key = {person.person_key: person for person in people if person.person_key}
    by_email: dict[str, list[Vacation]] = defaultdict(list)
    for vacation in vacations:
        if vacation.employee_email and normalize_key(vacation.request_type) == "vacaciones":
            by_email[vacation.employee_email.casefold()].append(vacation)
    conflicts: dict[tuple[int, str], list[Any]] = {}
    published = set()
    for shift in shifts:
        if not shift.person_key:
            continue
        person = by_key.get(shift.person_key)
        if person is None:
            continue
        if shift.kind != ShiftKind.SIN_PUBLICAR:
            published.add((person.sp_id, shift.day))
        if shift.kind != ShiftKind.TRABAJO or not person.email:
            continue
        overlapping = [
            vacation
            for vacation in by_email[person.email.casefold()]
            if vacation.start_date and vacation.end_date and vacation.start_date <= shift.day <= vacation.end_date
        ]
        if overlapping:
            conflicts[(person.sp_id, shift.day.isoformat())] = [
                person.name,
                shift.day.isoformat(),
                shift.raw_value or "Trabajo",
            ]
    return list(conflicts.values()), {key[0] for key in conflicts}, len(published)


def cruce_vacaciones_turnos(deps: Deps) -> Tool:
    async def handler(params: CruceVacacionesTurnosParams, ctx: ToolContext) -> ToolResult:
        start, end = params.resolve(ctx.now.date(), default_days=6)
        # La semántica de semana en planificación incluye lunes a domingo, también
        # los días futuros. No se confía en las fechas que haya inventado el modelo.
        week = requested_week(ctx.user_message, ctx.now.date())
        if week is not None:
            monday, sunday = week
            if (params.desde is not None and start != monday) or (params.hasta is not None and end != sunday):
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS,
                    {
                        "motivo": "Las fechas no coinciden con la semana solicitada.",
                        "desde_requerido": monday.isoformat(),
                        "hasta_requerido": sunday.isoformat(),
                    },
                )
            start, end = monday, sunday
        days = (end - start).days + 1
        if days < 1 or days > 93:
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS, "Indica un periodo de entre 1 y 93 días; no se recorta la consulta."
            )
        async with deps.db.session() as session:
            department = await resolve_department(session, params.departamento)
            if department.status is not ToolStatus.OK:
                return department_problem(department, params.departamento)
            query = select(Employee)
            if not params.incluir_inactivos:
                query = query.where(Employee.active.is_(True))
            if department.key:
                query = query.where(Employee.department_key == department.key)
            people = list((await session.scalars(query)).all())
            keys = {person.person_key for person in people if person.person_key}
            emails = {person.email.casefold() for person in people if person.email}
            if len(keys) != sum(bool(person.person_key) for person in people) or len(emails) != sum(
                bool(person.email) for person in people
            ):
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS,
                    "Hay identidades duplicadas en la plantilla seleccionada; no se puede acreditar el cruce.",
                )
            shifts = list(
                (
                    await session.scalars(
                        select(ShiftDay).where(
                            ShiftDay.person_key.in_(keys),
                            ShiftDay.day >= start,
                            ShiftDay.day <= end,
                        )
                    )
                ).all()
            )
            vacations = list(
                (
                    await session.scalars(
                        select(Vacation).where(
                            func.lower(Vacation.employee_email).in_(emails),
                            Vacation.start_date <= end,
                            Vacation.end_date >= start,
                        )
                    )
                ).all()
            )
            vacations = await confirmed_vacations(session, vacations)
            fresh = await deps.freshness(session, "empleados", "turnos", "vacaciones")
        rows, ids, published = _compare(people, shifts, vacations)
        missing = max(0, len(people) * days - published)
        summary = {
            "desde": start.isoformat(),
            "hasta": end.isoformat(),
            "dias_consultados": days,
            "plantilla_seleccionada": len(people),
            "personas_con_conflicto": len(ids),
            "dias_persona_con_conflicto": len(rows),
            "dias_persona_sin_turno_publicado": missing,
            "conflictos_por_fecha": dict(Counter(row[1] for row in rows)),
            "regla": "Conflicto solo si la misma persona tiene vacaciones aceptadas y turno de Trabajo el mismo día.",
            "limitacion": "Faltan turnos publicados: no se confirma ausencia de otros conflictos." if missing else None,
            **fresh,
        }
        checked_answer = (
            (
                f"Del {start.isoformat()} al {end.isoformat()} se observan {len(ids)} personas con conflicto "
                f"en {len(rows)} días-persona entre vacaciones aceptadas y turnos de Trabajo. "
                f"Faltan turnos publicados en {missing} días-persona; no se puede certificar la ausencia "
                "de otros conflictos ni una coordinación completa."
            )
            if missing
            else None
        )
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Vacaciones y turnos: coincidencias por día", ["Persona", "Fecha", "Turno"], rows),
            population_state(
                f"conflictos vacaciones turnos {start.isoformat()} a {end.isoformat()}",
                [person for person in people if person.sp_id in ids],
            ),
            verified_answer=checked_answer,
        )

    return Tool(
        "cruce_vacaciones_turnos",
        "Verifica incompatibilidades entre vacaciones aceptadas y turnos de Trabajo de un departamento "
        "en TODO el periodo, por persona y día; una intersección de poblaciones no demuestra este conflicto.",
        CruceVacacionesTurnosParams,
        handler,
        permission=Permission.TURNOS_LEER,
        required_permissions=frozenset({Permission.VACACIONES_LEER, Permission.EMPLEADOS_LEER}),
        verifies_request=_verifies_request,
        audit_resource="vacaciones_turnos",
    )
