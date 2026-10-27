"""Turnos: el día a día de cada persona y de cada departamento, y las ausencias."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from mia.sources.mappers.hr import ShiftKind
from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import ShiftDay
from mia.modules.rrhh.common import (
    MAX_ROWS_FOR_MODEL,
    Deps,
    Periodo,
    PersonaParams,
    days_between,
    fmt_date,
    focus_person,
    freshness,
    merge_periods,
    person_problem,
    resolve_person,
    table,
)
from mia.text import normalize_key

DAY_NAMES = {
    "L": "lunes",
    "M": "martes",
    "X": "miércoles",
    "J": "jueves",
    "V": "viernes",
    "S": "sábado",
    "D": "domingo",
}
ABSENCE_KINDS = (ShiftKind.BAJA, ShiftKind.VACACIONES, ShiftKind.PERMISO, ShiftKind.ASUNTOS_PROPIOS)


def day_view(s: ShiftDay) -> dict[str, Any]:
    return {
        "fecha": s.day.isoformat(),
        "dia": DAY_NAMES.get(s.weekday, s.weekday),
        "tipo": s.kind,
        "horario": s.raw_value,
        "inicio": s.start_time,
        "fin": s.end_time,
        "area": s.area,
        "comentario": s.comment,
    }


# ------------------------------------------------------------------ turnos de una persona
class TurnosPersonaParams(PersonaParams, Periodo):
    pass


def turnos_persona(deps: Deps) -> Tool:
    async def handler(p: TurnosPersonaParams, ctx: ToolContext) -> ToolResult:
        start, end = p.resolve(ctx.now.date(), default_days=0 if p.desde else 6)
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            shifts: list[ShiftDay] = []
            if e.person_key:
                stmt = (
                    select(ShiftDay)
                    .where(ShiftDay.person_key == e.person_key, ShiftDay.day.between(start, end))
                    .order_by(ShiftDay.day)
                )
                shifts = list((await db.scalars(stmt)).all())
            fresh = await freshness(db, "turnos")
        by_day = {s.day: s for s in shifts}
        missing = [d.isoformat() for d in days_between(start, end) if d not in by_day]
        summary: dict[str, Any] = {
            "persona": e.name,
            "empleado_id": e.sp_id,
            "desde": start.isoformat(),
            "hasta": end.isoformat(),
            "dias": [day_view(s) for s in shifts],
            **fresh,
        }
        if missing:
            summary["dias_sin_turno_publicado"] = missing
        rows = [[fmt_date(s.day), DAY_NAMES.get(s.weekday), s.kind, s.raw_value, s.comment] for s in shifts]
        state = {**focus_person(e), "foco_periodo": {"desde": start.isoformat(), "hasta": end.isoformat()}}
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Turnos de {e.name}", ["Fecha", "Día", "Tipo", "Turno", "Comentario"], rows),
            state,
        )

    return Tool(
        "turnos_persona",
        "Turnos de una persona entre dos fechas (por defecto, los próximos 7 días). Distingue trabajo, "
        "descanso, vacaciones, baja, permisos y días sin turno publicado.",
        TurnosPersonaParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ turnos de un departamento
class TurnosDepartamentoParams(BaseModel):
    departamento: str = Field(description="Departamento")
    fecha: date | None = Field(default=None, description="Día AAAA-MM-DD (por defecto hoy)")
    tipo: str | None = Field(default=None, description="Filtrar por tipo: Trabajo, Descanso, Vacaciones, Baja/IT…")


def turnos_departamento(deps: Deps) -> Tool:
    async def handler(p: TurnosDepartamentoParams, ctx: ToolContext) -> ToolResult:
        day = p.fecha or ctx.now.date()
        key = normalize_key(p.departamento)
        async with deps.db.session() as db:
            stmt = (
                select(ShiftDay)
                .where(ShiftDay.day == day, ShiftDay.department_key.like(f"%{key}%"))
                .order_by(ShiftDay.kind, ShiftDay.employee_name)
            )
            shifts = list((await db.scalars(stmt)).all())
            fresh = await freshness(db, "turnos")
        if p.tipo:
            wanted = normalize_key(p.tipo)
            shifts = [s for s in shifts if wanted in normalize_key(s.kind)]
        if not shifts:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                {"mensaje": f"No hay turnos publicados para {p.departamento} el {fmt_date(day)}.", **fresh},
            )
        groups: dict[str, list[str]] = defaultdict(list)
        for s in shifts:
            groups[s.kind].append(
                f"{s.employee_name} ({s.raw_value})" if s.kind == ShiftKind.TRABAJO else str(s.employee_name)
            )
        summary: dict[str, Any] = {
            "fecha": day.isoformat(),
            "departamento": shifts[0].department,
            "recuento_por_tipo": {k: len(v) for k, v in groups.items()},
            **fresh,
        }
        if len(shifts) <= MAX_ROWS_FOR_MODEL:
            summary["personas_por_tipo"] = dict(groups)
        rows = [[s.employee_name, s.kind, s.raw_value, s.area, s.comment] for s in shifts]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"{shifts[0].department} · {fmt_date(day)}",
                ["Persona", "Tipo", "Turno", "Área", "Comentario"],
                rows,
            ),
            {"foco_departamento": shifts[0].department, "foco_periodo": {"desde": day.isoformat()}},
        )

    return Tool(
        "turnos_departamento",
        "Quién trabaja, descansa o está ausente en un departamento un día concreto.",
        TurnosDepartamentoParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ ausencias
class AusenciasParams(Periodo):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    tipos: list[str] | None = Field(
        default=None,
        description="Tipos de ausencia: Baja/IT, Vacaciones, Permiso, Asuntos propios (por defecto todos)",
    )


def ausencias(deps: Deps) -> Tool:
    async def handler(p: AusenciasParams, ctx: ToolContext) -> ToolResult:
        start, end = p.resolve(ctx.now.date())
        kinds = [k for k in ABSENCE_KINDS if not p.tipos or any(normalize_key(t) in normalize_key(k) for t in p.tipos)]
        async with deps.db.session() as db:
            stmt = select(ShiftDay).where(ShiftDay.day.between(start, end), ShiftDay.kind.in_(kinds))
            if p.departamento:
                stmt = stmt.where(ShiftDay.department_key.like(f"%{normalize_key(p.departamento)}%"))
            shifts = list((await db.scalars(stmt.order_by(ShiftDay.employee_name, ShiftDay.day))).all())
            fresh = await freshness(db, "turnos")
        grouped: dict[tuple[str | None, str | None, str], list[date]] = defaultdict(list)
        for s in shifts:
            grouped[(s.employee_name, s.department, s.kind)].append(s.day)
        periods: list[dict[str, Any]] = [
            {
                "persona": name,
                "departamento": dept,
                "tipo": kind,
                "desde": a.isoformat(),
                "hasta": b.isoformat(),
                "dias": (b - a).days + 1,
            }
            for (name, dept, kind), days in grouped.items()
            for a, b in merge_periods(days)
        ]
        people_by_kind: dict[str, set[str]] = defaultdict(set)
        for name, _, kind in grouped:
            people_by_kind[kind].add(str(name))
        summary: dict[str, Any] = {
            "desde": start.isoformat(),
            "hasta": end.isoformat(),
            "departamento": p.departamento,
            "personas_por_tipo": {k: len(v) for k, v in people_by_kind.items()},
            **fresh,
        }
        if len(periods) <= MAX_ROWS_FOR_MODEL:
            summary["periodos"] = periods
        rows = [
            [
                x["persona"],
                x["departamento"],
                x["tipo"],
                fmt_date(date.fromisoformat(x["desde"])),
                fmt_date(date.fromisoformat(x["hasta"])),
                x["dias"],
            ]
            for x in periods
        ]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Ausencias", ["Persona", "Departamento", "Tipo", "Desde", "Hasta", "Días"], rows),
            {"foco_periodo": {"desde": start.isoformat(), "hasta": end.isoformat()}},
        )

    return Tool(
        "ausencias",
        "Personas ausentes (baja/IT, vacaciones, permisos, asuntos propios) según los turnos publicados, "
        "agrupadas en periodos. Por defecto hoy.",
        AusenciasParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (turnos_persona, turnos_departamento, ausencias):
        registry.register(factory(deps))
