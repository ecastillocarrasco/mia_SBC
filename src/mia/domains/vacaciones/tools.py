"""Vacaciones: solicitudes, saldos y reincorporación efectiva."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, Vacation, VacationBalance
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    CohortParams,
    Deps,
    Periodo,
    PersonaParams,
    department_problem,
    employees_for,
    fmt_date,
    focus_person,
    no_population,
    person_problem,
    population_state,
    previous_population,
    resolve_department,
    resolve_person,
    table,
)
from mia.domains.turnos import absence_periods
from mia.domains.turnos.tools import DAY_NAMES
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
class VacacionesParams(_OptionalPerson, Periodo, CohortParams):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    estado: Literal["aceptadas", "pendientes", "rechazadas", "todas"] = Field(
        default="aceptadas", description="Por defecto solo las aceptadas"
    )
    tipo: Literal["vacaciones", "asuntos propios", "todos"] = "todos"


def _people_and_overlaps(rows: list[Vacation], today: date) -> tuple[int, int]:
    """Personas distintas y solicitudes que se solapan con otra de la misma persona."""
    by_person: dict[str, list[Vacation]] = defaultdict(list)
    for v in rows:
        by_person[v.employee_email or normalize_key(v.employee_name)].append(v)
    overlapping = 0
    for vs in by_person.values():
        ordered = sorted(vs, key=lambda x: x.start_date or today)
        overlapping += sum(
            1 for a, b in pairwise(ordered) if a.end_date and b.start_date and b.start_date <= a.end_date
        )
    return len(by_person), overlapping


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
            if p.sobre_resultado_anterior or p.resultado:
                if (previous := previous_population(ctx, p.resultado)) is None:
                    return no_population()
                stmt = stmt.where(Vacation.employee_email.in_(previous["emails"]))
            rows = list((await db.scalars(stmt.order_by(Vacation.start_date))).all())
            fresh = await deps.freshness(db, "vacaciones")
        if p.estado != "todas":
            rows = [v for v in rows if normalize_key(v.status) == ESTADOS[p.estado]]
        if p.tipo != "todos":
            rows = [v for v in rows if normalize_key(v.request_type) == normalize_key(p.tipo)]
        async with deps.db.session() as db:
            people = await employees_for(db, emails={v.employee_email for v in rows if v.employee_email})
        state.update(population_state(f"vacaciones ({p.estado})", people))
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
        persons, overlapping = _people_and_overlaps(rows, today)
        summary: dict[str, Any] = {
            "personas_distintas": persons,
            "solicitudes": len(items),
            "solicitudes_solapadas": overlapping,
            "estado": p.estado,
            "nota": "Cuenta personas con «personas_distintas»; una persona puede tener varias solicitudes.",
            **fresh,
        }
        if len(items) <= MAX_ROWS_FOR_MODEL:
            summary["detalle"] = items
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
class SaldoParams(_OptionalPerson, CohortParams):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    solo_negativos: bool = Field(default=False, description="Solo saldos por debajo de cero")
    solo_disponibles: bool = Field(default=False, description="Solo quien tiene saldo disponible (mayor que cero)")
    ordenar: Literal["menor", "mayor"] = Field(default="menor", description="«mayor» para quién tiene más días")
    limite: int | None = Field(default=None, ge=1, le=200, description="Quedarse con los N primeros tras ordenar")
    incluir_inactivos: bool = Field(default=False, description="Por defecto solo plantilla activa (POB-001)")
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
            if p.solo_disponibles:
                stmt = stmt.where(VacationBalance.current_balance > 0)
            if who is None and not p.incluir_inactivos:
                # POB-001, como el sistema anterior: el saldo de quien ya no está en plantilla no cuenta.
                active = select(Employee.email).where(Employee.active.is_(True), Employee.email.is_not(None))
                stmt = stmt.where(VacationBalance.employee_email.in_(active))
            if p.sobre_resultado_anterior or p.resultado:
                if (previous := previous_population(ctx, p.resultado)) is None:
                    return no_population()
                stmt = stmt.where(VacationBalance.employee_email.in_(previous["emails"]))
            order = VacationBalance.current_balance.desc() if p.ordenar == "mayor" else VacationBalance.current_balance
            rows = list((await db.scalars(stmt.order_by(order, VacationBalance.employee_name))).all())
            if p.limite:
                top_value = rows[p.limite - 1].current_balance if len(rows) >= p.limite else None
                # Empates en el corte: se incluyen todos los que tienen el mismo saldo (como el sistema anterior).
                rows = [r for i, r in enumerate(rows) if i < p.limite or r.current_balance == top_value]
            people = await employees_for(db, emails={b.employee_email for b in rows if b.employee_email})
            state.update(population_state(f"saldos {year}", people))
            fresh = await deps.freshness(db, f"saldo_vacaciones_{year}")
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
                "consumido": (
                    round(b.total_balance - b.current_balance, 2)
                    if b.total_balance is not None and b.current_balance is not None
                    else None
                ),
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


def reincorporacion(deps: Deps) -> Tool:
    async def handler(p: ReincorporacionParams, ctx: ToolContext) -> ToolResult:
        ref = p.fecha_referencia or ctx.now.date()
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            if not e.person_key:
                return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": f"No puedo cruzar los turnos de {e.name}."})
            # Ausencia en curso o la próxima que empiece en los 60 días siguientes (según turnos).
            periods = await absence_periods(db, lo=ref, hi=ref + timedelta(days=60), person_keys=[e.person_key])
            vacation = None
            if e.email:
                vacation = await db.scalar(
                    select(Vacation)
                    .where(Vacation.employee_email == e.email, Vacation.end_date >= ref)
                    .order_by(Vacation.start_date)
                    .limit(1)
                )
            fresh = await deps.freshness(db, "turnos", "vacaciones")
        periods.sort(key=lambda x: x.start)
        period = periods[0] if periods else None
        if period is None and not (vacation and normalize_key(vacation.status) == "aceptada"):
            return ToolResult(
                ToolStatus.OK,
                {
                    "persona": e.name,
                    "ausente": False,
                    "mensaje": f"{e.name} no está ausente ni tiene ausencias próximas publicadas.",
                    **fresh,
                },
                state_updates=focus_person(e),
            )
        summary: dict[str, Any] = {
            "persona": e.name,
            "regla": "VAC-001: la reincorporación es el primer turno de Trabajo tras el fin de la ausencia.",
            **fresh,
        }
        if period is not None:
            summary.update(
                motivo=period.kind,
                ausente_desde=period.start.isoformat(),
                ausente_hasta=period.end.isoformat(),
                en_curso=period.start <= ref <= period.end,
            )
            back = period.return_shift
        else:
            assert vacation is not None  # noqa: S101
            summary.update(
                motivo="Vacaciones (solicitud aceptada, aún sin reflejo en turnos)",
                ausente_desde=vacation.start_date.isoformat() if vacation.start_date else None,
                ausente_hasta=vacation.end_date.isoformat() if vacation.end_date else None,
            )
            back = None
        if back is not None:
            summary["reincorporacion"] = {
                "fecha": back.day.isoformat(),
                "dia": DAY_NAMES.get(back.weekday or ""),
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
        "Cuándo se reincorpora UNA persona tras vacaciones, baja o permiso: primer turno de trabajo "
        "publicado después de la ausencia. Para listas de varias personas usa 'reincorporaciones'.",
        ReincorporacionParams,
        handler,
        permission=Permission.VACACIONES_LEER,
        audit_resource="vacaciones",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (solicitudes, saldos, reincorporacion):
        registry.register(factory(deps))
