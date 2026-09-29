"""«¿Con quién coincide X el lunes?»: compañeros que trabajan a la vez que una persona, en su departamento."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, ShiftDay
from mia.domains.common import (
    ActivosParams,
    Deps,
    PersonaParams,
    active_person_keys,
    fmt_date,
    focus_person,
    person_problem,
    resolve_person,
    table,
)
from mia.domains.turnos.tools import _minutes
from mia.sources.mappers.hr import ShiftKind


class CompanerosParams(PersonaParams, ActivosParams):
    fecha: date | None = Field(default=None, description="Día (por defecto hoy)")
    mismo_departamento: bool = Field(default=True, description="false para incluir a todos los departamentos")


def _span(s: ShiftDay) -> tuple[int, int] | None:
    start, end = _minutes(s.start_time), _minutes(s.end_time)
    if start is None or end is None:
        return None
    return start, end if end > start else end + 24 * 60  # los turnos de noche acaban al día siguiente


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def companeros_de_turno(deps: Deps) -> Tool:
    async def handler(p: CompanerosParams, ctx: ToolContext) -> ToolResult:
        day = p.fecha or ctx.now.date()
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e: Employee = match.employee
            mine = (
                (
                    await db.scalars(
                        select(ShiftDay).where(
                            ShiftDay.person_key == e.person_key, ShiftDay.day == day, ShiftDay.kind == ShiftKind.TRABAJO
                        )
                    )
                ).first()
                if e.person_key
                else None
            )
            if mine is None or (span := _span(mine)) is None:
                return ToolResult(
                    ToolStatus.NOT_FOUND,
                    {"mensaje": f"{e.name} no tiene un turno de trabajo con horario el {fmt_date(day)}."},
                )
            stmt = select(ShiftDay).where(
                ShiftDay.day == day, ShiftDay.kind == ShiftKind.TRABAJO, ShiftDay.person_key != e.person_key
            )
            if p.mismo_departamento:
                stmt = stmt.where(ShiftDay.department_key == mine.department_key)
            if not p.incluir_inactivos:
                stmt = stmt.where(ShiftDay.person_key.in_(active_person_keys()))
            others = list((await db.scalars(stmt.order_by(ShiftDay.employee_name))).all())
        together = []
        for s in others:
            other_span = _span(s)
            if other_span and (minutes := _overlap(span, other_span)):
                together.append(
                    {
                        "persona": s.employee_name,
                        "departamento": s.department,
                        "turno": s.raw_value,
                        "horas_coincidencia": round(minutes / 60, 1),
                    }
                )
        summary: dict[str, Any] = {
            "persona": e.name,
            "fecha": day.isoformat(),
            "su_turno": mine.raw_value,
            "coinciden": len(together),
            "companeros": together[:80],
        }
        rows = [[t["persona"], t["departamento"], t["turno"], t["horas_coincidencia"]] for t in together]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Coinciden con {e.name} · {fmt_date(day)}", ["Persona", "Departamento", "Turno", "Horas juntos"], rows
            ),
            focus_person(e),
        )

    return Tool(
        "companeros_de_turno",
        "Quién trabaja a la vez que una persona un día (mismo departamento por defecto), con las horas que coinciden. "
        "Para «¿con quién coincide Ana el lunes?» o «¿quién está en mi turno?».",
        CompanerosParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )
