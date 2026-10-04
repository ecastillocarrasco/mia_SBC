"""Vacaciones: solicitudes, saldos y reincorporación efectiva."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, ShiftDay, Vacation, VacationBalance
from mia.modules.rrhh.common import (
    MAX_ROWS_FOR_MODEL,
    Deps,
    Periodo,
    PersonaParams,
    department_problem,
    fmt_date,
    focus_person,
    freshness,
    person_problem,
    resolve_department,
    resolve_person,
    table,
)
from mia.modules.rrhh.turnos import ABSENCE_KINDS
from mia.modules.rrhh.turnos.tools import DAY_NAMES
from mia.sources.mappers.hr import ShiftKind
from mia.text import normalize_key

ESTADOS = {"aceptadas": "aceptada", "pendientes": "pendiente", "rechazadas": "rechazada"}


class _OptionalPerson(BaseModel):
    empleado_id: int | None = Field(default=None, description="ID de la persona (foco o búsqueda previa)")
    nombre: str | None = Field(default=None, description="Nombre de la persona (opcional)")

    def person(self) -> PersonaParams | None:
        if self.empleado_id is None and not (self.nombre or "").strip():
            return None
        return PersonaParams(empleado_id=self.empleado_id, nombre=self.nombre)


# ------------------------------------------------------------------ solicitudes
class VacacionesParams(_OptionalPerson, Periodo):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    estado: Literal["aceptadas", "pendientes", "rechazadas", "todas"] = Field(
        default="aceptadas", description="Por defecto solo las aceptadas"
    )
    tipo: Literal["vacaciones", "asuntos propios", "todos"] = "todos"


def solicitudes(deps: Deps) -> Tool:
    async def handler(p: VacacionesParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        state: dict[str, Any] = {}
        async with deps.db.session() as db:
            stmt = select(Vacation)
            who = p.person()
            employee: Employee | None = None
            if who is not None:
                match = await resolve_person(db, who)
                if match.employee is None:
                    return person_problem(match, who.nombre)
                employee = match.employee
                if not employee.email:
                    return ToolResult(
                        ToolStatus.NOT_FOUND,
                        {"mensaje": f"{employee.name} no tiene email para cruzar sus vacaciones."},
                    )
                stmt = stmt.where(Vacation.employee_email == employee.email)
                state.update(focus_person(employee))
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            if dept.key:
                stmt = stmt.where(Vacation.department_key == dept.key)
            if p.desde or p.hasta or employee is None:
                start, end = p.resolve(today, default_days=30)
                stmt = stmt.where(Vacation.start_date <= end, Vacation.end_date >= start)
                state["foco_periodo"] = {"desde": start.isoformat(), "hasta": end.isoformat()}
            else:
                stmt = stmt.where(Vacation.end_date >= today)  # de una persona: en curso y próximas
            rows = list((await db.scalars(stmt.order_by(Vacation.start_date))).all())
            fresh = await freshness(db, "vacaciones")
        if p.estado != "todas":
            rows = [v for v in rows if normalize_key(v.status) == ESTADOS[p.estado]]
        if p.tipo != "todos":
            rows = [v for v in rows if normalize_key(v.request_type) == normalize_key(p.tipo)]
        items = [
            {
                "persona": v.employee_name,
                "departamento": v.department,
                "desde": fmt_date(v.start_date),
                "hasta": fmt_date(v.end_date),
                "dias": v.total_days,
                "estado": v.status,
                "tipo": v.request_type,
            }
            for v in rows
        ]
        summary: dict[str, Any] = {"total": len(items), "estado": p.estado, **fresh}
        if len(items) <= MAX_ROWS_FOR_MODEL:
            summary["solicitudes"] = items
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                "Vacaciones",
                ["Persona", "Departamento", "Desde", "Hasta", "Días", "Estado", "Tipo"],
                [list(i.values()) for i in items],
            ),
            state,
        )

    return Tool(
        "vacaciones",
        "Solicitudes de vacaciones y asuntos propios de una persona, un departamento o un periodo. "
        "Por defecto solo aceptadas; de una persona sin fechas, las en curso y próximas.",
        VacacionesParams,
        handler,
        permission=Permission.VACACIONES_LEER,
        audit_resource="vacaciones",
    )


# ------------------------------------------------------------------ saldos
class SaldoParams(_OptionalPerson):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    solo_negativos: bool = Field(default=False, description="Solo saldos por debajo de cero")
    anio: int | None = Field(default=None, description="Año del saldo (por defecto el actual)")


def saldos(deps: Deps) -> Tool:
    async def handler(p: SaldoParams, ctx: ToolContext) -> ToolResult:
        year = p.anio or ctx.now.year
        state: dict[str, Any] = {}
        async with deps.db.session() as db:
            stmt = select(VacationBalance).where(VacationBalance.year == year)
            who = p.person()
            if who is not None:
                match = await resolve_person(db, who)
                if match.employee is None:
                    return person_problem(match, who.nombre)
                stmt = stmt.where(VacationBalance.employee_email == match.employee.email)
                state.update(focus_person(match.employee))
            elif p.departamento:
                stmt = stmt.where(VacationBalance.department.ilike(f"%{p.departamento}%"))
            if p.solo_negativos:
                stmt = stmt.where(VacationBalance.current_balance < 0)
            rows = list((await db.scalars(stmt.order_by(VacationBalance.current_balance))).all())
            fresh = await freshness(db, f"saldo_vacaciones_{year}")
        if not rows:
            return ToolResult(
                ToolStatus.NOT_FOUND, {"mensaje": f"No hay saldos de {year} con esos criterios.", **fresh}
            )
        items = [
            {
                "persona": b.employee_name,
                "departamento": b.department,
                "saldo_actual": b.current_balance,
                "saldo_total": b.total_balance,
            }
            for b in rows
        ]
        summary: dict[str, Any] = {
            "anio": year,
            "total_personas": len(items),
            "con_saldo_negativo": sum(1 for b in rows if (b.current_balance or 0) < 0),
            "nota": "Saldo negativo = días disfrutados de más: comunícalo como negativo (VAC-002).",
            **fresh,
        }
        if len(items) <= MAX_ROWS_FOR_MODEL:
            summary["saldos"] = items
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Saldo de vacaciones {year}",
                ["Persona", "Departamento", "Saldo actual", "Saldo total"],
                [list(i.values()) for i in items],
            ),
            state,
        )

    return Tool(
        "saldo_vacaciones",
        "Saldo de vacaciones (puede ser negativo) de una persona, un departamento o toda la plantilla.",
        SaldoParams,
        handler,
        permission=Permission.VACACIONES_LEER,
        audit_resource="vacaciones",
    )


# ------------------------------------------------------------------ reincorporación (VAC-001)
class ReincorporacionParams(PersonaParams):
    fecha_referencia: date | None = Field(default=None, description="Por defecto hoy")


def _absence_end(shifts: list[ShiftDay], start: date) -> date | None:
    """Último día de la ausencia que incluye ``start`` según los turnos (días consecutivos de ausencia)."""
    by_day = {s.day: s for s in shifts}
    day = start
    if day not in by_day or by_day[day].kind not in ABSENCE_KINDS:
        return None
    continues = (*ABSENCE_KINDS, ShiftKind.DESCANSO)
    while (day + timedelta(days=1)) in by_day and by_day[day + timedelta(days=1)].kind in continues:
        day += timedelta(days=1)
    while by_day[day].kind == ShiftKind.DESCANSO:  # los descansos al final no alargan la ausencia
        day -= timedelta(days=1)
    return day


def reincorporacion(deps: Deps) -> Tool:
    async def handler(p: ReincorporacionParams, ctx: ToolContext) -> ToolResult:
        ref = p.fecha_referencia or ctx.now.date()
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            if not e.person_key:
                return ToolResult(
                    ToolStatus.NOT_FOUND, {"mensaje": f"No puedo cruzar los turnos de {e.name}."}
                )
            shifts = list(
                (
                    await db.scalars(
                        select(ShiftDay)
                        .where(ShiftDay.person_key == e.person_key, ShiftDay.day >= ref - timedelta(days=1))
                        .order_by(ShiftDay.day)
                    )
                ).all()
            )
            vacation = None
            if e.email:
                vacation = await db.scalar(
                    select(Vacation)
                    .where(Vacation.employee_email == e.email, Vacation.end_date >= ref)
                    .order_by(Vacation.start_date)
                    .limit(1)
                )
            fresh = await freshness(db, "turnos", "vacaciones")
        today_shift = next((s for s in shifts if s.day == ref), None)
        reason, end = None, None
        if today_shift and today_shift.kind in ABSENCE_KINDS:
            reason, end = today_shift.kind, _absence_end(shifts, ref)
        elif vacation and normalize_key(vacation.status) == "aceptada" and vacation.end_date:
            reason, end = "Vacaciones", vacation.end_date
        if end is None:
            return ToolResult(
                ToolStatus.OK,
                {
                    "persona": e.name,
                    "ausente": False,
                    "mensaje": f"{e.name} no está ausente ni tiene vacaciones aceptadas próximas.",
                    **fresh,
                },
                state_updates=focus_person(e),
            )
        back = next((s for s in shifts if s.day > end and s.kind == ShiftKind.TRABAJO), None)
        summary: dict[str, Any] = {
            "persona": e.name,
            "motivo": reason,
            "ausente_hasta": end.isoformat(),
            "regla": "VAC-001: la reincorporación es el primer turno de Trabajo tras el fin de la ausencia.",
            **fresh,
        }
        if back:
            summary["reincorporacion"] = {
                "fecha": back.day.isoformat(),
                "dia": DAY_NAMES.get(back.weekday),
                "turno": back.raw_value,
            }
        else:
            summary["reincorporacion"] = None
            summary["mensaje"] = (
                "Todavía no hay publicado ningún turno de trabajo posterior: no se puede afirmar la fecha."
            )
        return ToolResult(ToolStatus.OK, summary, {"type": "reincorporation", **summary}, focus_person(e))

    return Tool(
        "reincorporacion",
        "Cuándo se reincorpora una persona tras vacaciones, baja o permiso: primer turno de trabajo "
        "publicado después de la ausencia.",
        ReincorporacionParams,
        handler,
        permission=Permission.VACACIONES_LEER,
        audit_resource="vacaciones",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (solicitudes, saldos, reincorporacion):
        registry.register(factory(deps))
