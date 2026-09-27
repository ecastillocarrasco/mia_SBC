"""Turnos: el día a día de cada persona y de la plantilla, ausencias y reincorporaciones."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import ShiftDay
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    Deps,
    Periodo,
    PersonaParams,
    days_between,
    fmt_date,
    focus_person,
    person_problem,
    resolve_person,
    table,
)
from mia.domains.turnos.periods import ABSENCE_KINDS, AbsencePeriod, absence_periods
from mia.sources.mappers.hr import ShiftKind
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

# TUR-001: franjas por hora de INICIO del turno (misma definición que el sistema anterior).
FRANJAS: dict[str, tuple[int, int]] = {
    "mañana": (5 * 60, 12 * 60),
    "tarde": (12 * 60, 18 * 60),
    "noche": (18 * 60, 5 * 60),
}
Franja = Literal["mañana", "tarde", "noche"]


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":", 1)
    return int(h) * 60 + int(m) if h.isdigit() and m.isdigit() else None


def starts_in(shift: ShiftDay, franja: str) -> bool:
    start = _minutes(shift.start_time)
    if start is None:
        return False
    lo, hi = FRANJAS[franja]
    return lo <= start < hi if lo < hi else start >= lo or start < hi


def works_at(shift: ShiftDay, minute: int) -> bool:
    """TUR-002: presencia por solape (un turno 22:00-06:00 cubre las 02:00)."""
    start, end = _minutes(shift.start_time), _minutes(shift.end_time)
    if start is None or end is None:
        return False
    if end <= start:
        end += 24 * 60
    return start <= minute < end or start <= minute + 24 * 60 < end


def franja_of(shift: ShiftDay) -> str | None:
    return next((f for f in FRANJAS if starts_in(shift, f)), None)


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


async def resolve_shift_department(
    db: AsyncSession, query: str | None
) -> tuple[ToolStatus, str | None, list[str]]:
    """Departamento tal como aparece en Turnos. Devuelve (estado, clave, opciones)."""
    if not (query or "").strip():
        return ToolStatus.OK, None, []
    rows = (await db.execute(select(ShiftDay.department, ShiftDay.department_key).distinct())).all()
    known = {key: name for name, key in rows if key and name}
    wanted = normalize_key(query)
    if wanted in known:
        return ToolStatus.OK, wanted, []
    partial = [k for k in known if wanted in k or k in wanted]
    if len(partial) == 1:
        return ToolStatus.OK, partial[0], []
    options = sorted(known[k] for k in (partial or known))
    return (ToolStatus.AMBIGUOUS if partial else ToolStatus.NOT_FOUND), None, options


def department_not_found(status: ToolStatus, query: str | None, options: list[str]) -> ToolResult:
    """Nunca se convierte en «no hay turnos»: el problema es el nombre del departamento."""
    verb = (
        "Hay varios departamentos que encajan"
        if status is ToolStatus.AMBIGUOUS
        else "No existe ese departamento"
    )
    return ToolResult(
        status, {"mensaje": f"{verb} («{query}»). No es que no haya turnos.", "departamentos": options}
    )


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
            fresh = await deps.freshness(db, "turnos")
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
        "Turnos de una persona entre dos fechas (por defecto, los próximos 7 días): trabajo, descanso, "
        "vacaciones, baja, permisos y días sin turno publicado. Para 'cuándo libra' o 'próximo turno'.",
        TurnosPersonaParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ turnos de un día
class TurnosDiaParams(BaseModel):
    fecha: date | None = Field(default=None, description="Día AAAA-MM-DD (por defecto hoy)")
    departamento: str | None = Field(
        default=None, description="Departamento (opcional; sin él, toda la plantilla)"
    )
    franja: Franja | None = Field(
        default=None,
        description="Turno de mañana (empieza 05:00-11:59), tarde (12:00-17:59) o noche (18:00-04:59)",
    )
    hora: str | None = Field(
        default=None, description="HH:MM para saber quién está trabajando a esa hora (presencia, no inicio)"
    )
    tipo: str | None = Field(
        default=None, description="Trabajo, Descanso, Vacaciones, Baja/IT… (por defecto todos)"
    )


def turnos_dia(deps: Deps) -> Tool:
    async def handler(p: TurnosDiaParams, ctx: ToolContext) -> ToolResult:
        day = p.fecha or ctx.now.date()
        async with deps.db.session() as db:
            status, dept_key, options = await resolve_shift_department(db, p.departamento)
            if status is not ToolStatus.OK:
                return department_not_found(status, p.departamento, options)
            stmt = select(ShiftDay).where(ShiftDay.day == day)
            if dept_key:
                stmt = stmt.where(ShiftDay.department_key == dept_key)
            shifts = list(
                (await db.scalars(stmt.order_by(ShiftDay.department, ShiftDay.employee_name))).all()
            )
            fresh = await deps.freshness(db, "turnos")
        if not shifts:
            scope = f"en {p.departamento}" if p.departamento else "en ninguna parte de la plantilla"
            return ToolResult(
                ToolStatus.NOT_FOUND,
                {"mensaje": f"No hay turnos publicados el {fmt_date(day)} {scope}.", **fresh},
            )
        selected = shifts
        criteria = []
        if p.tipo:
            wanted = normalize_key(p.tipo)
            selected = [s for s in selected if wanted in normalize_key(s.kind)]
            criteria.append(f"tipo {p.tipo}")
        if p.franja:
            selected = [s for s in selected if s.kind == ShiftKind.TRABAJO and starts_in(s, p.franja)]
            criteria.append(f"turno de {p.franja} (por hora de inicio)")
        if p.hora and (minute := _minutes(p.hora)) is not None:
            selected = [s for s in selected if s.kind == ShiftKind.TRABAJO and works_at(s, minute)]
            criteria.append(f"trabajando a las {p.hora}")
        working = [s for s in shifts if s.kind == ShiftKind.TRABAJO]
        summary: dict[str, Any] = {
            "fecha": day.isoformat(),
            "departamento": shifts[0].department if dept_key else "toda la plantilla",
            "criterio": ", ".join(criteria) or "todos los turnos del día",
            "total_seleccionado": len(selected),
            "seleccion_por_departamento": dict(
                Counter(s.department or "Sin dato" for s in selected).most_common()
            ),
            "contexto_del_dia": {
                "por_tipo": dict(Counter(s.kind for s in shifts).most_common()),
                "trabajando_por_franja": dict(Counter(franja_of(s) or "sin horario" for s in working)),
            },
            **fresh,
        }
        if len(selected) <= MAX_ROWS_FOR_MODEL:
            summary["personas"] = [
                {
                    "nombre": s.employee_name,
                    "departamento": s.department,
                    "tipo": s.kind,
                    "turno": s.raw_value,
                }
                for s in selected
            ]
        rows = [[s.employee_name, s.department, s.kind, s.raw_value, s.area, s.comment] for s in selected]
        state: dict[str, Any] = {"foco_periodo": {"desde": day.isoformat()}}
        if dept_key:
            state["foco_departamento"] = shifts[0].department
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Turnos {fmt_date(day)}",
                ["Persona", "Departamento", "Tipo", "Turno", "Área", "Comentario"],
                rows,
            ),
            state,
        )

    return Tool(
        "turnos_dia",
        "Quién trabaja, descansa o está ausente un día, en toda la plantilla o en un departamento. Filtra "
        "por turno de mañana/tarde/noche (hora de inicio) o por quién está trabajando a una hora.",
        TurnosDiaParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ ausencias
def _period_view(p: AbsencePeriod, today: date, lo: date, hi: date) -> dict[str, Any]:
    view: dict[str, Any] = {
        "persona": p.name,
        "departamento": p.department,
        "tipo": p.kind,
        "desde": p.start.isoformat(),
        "hasta": p.end.isoformat(),
        "dias": p.days,
        "dias_en_el_periodo_consultado": p.days_within(lo, hi),
        "en_curso": p.start <= today <= p.end,
    }
    if p.starts_before_data:
        view["nota"] = "empezó antes del histórico disponible: puede ser más larga"
    if p.return_shift is not None:
        view["vuelve"] = {"fecha": p.return_shift.day.isoformat(), "turno": p.return_shift.raw_value}
    return view


class AusenciasParams(Periodo):
    empleado_id: int | None = Field(default=None, description="Persona concreta (del foco o de una búsqueda)")
    nombre: str | None = Field(default=None, description="Nombre de la persona, si no hay empleado_id")
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    tipos: list[str] | None = Field(
        default=None, description="Baja/IT, Vacaciones, Permiso, Asuntos propios (por defecto todos)"
    )
    ordenar_por: Literal["duracion", "inicio"] = Field(
        default="duracion", description="Por defecto, las más largas"
    )


def ausencias(deps: Deps) -> Tool:
    async def handler(p: AusenciasParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        kinds = tuple(
            k
            for k in ABSENCE_KINDS
            if not p.tipos or any(normalize_key(t) in normalize_key(k) for t in p.tipos)
        )
        state: dict[str, Any] = {}
        async with deps.db.session() as db:
            person_keys = None
            if p.empleado_id is not None or (p.nombre or "").strip():
                match = await resolve_person(db, PersonaParams(empleado_id=p.empleado_id, nombre=p.nombre))
                if match.employee is None:
                    return person_problem(match, p.nombre)
                person_keys = [match.employee.person_key] if match.employee.person_key else []
                state.update(focus_person(match.employee))
                # De una persona sin fechas: su historial del año en curso.
                default_lo = date(today.year, 1, 1)
                lo, hi = (p.desde or default_lo), (p.hasta or today)
            else:
                lo, hi = p.resolve(today)
            dept_key = None
            if p.departamento:
                status, dept_key, options = await resolve_shift_department(db, p.departamento)
                if status is not ToolStatus.OK:
                    return department_not_found(status, p.departamento, options)
            periods = await absence_periods(
                db, lo=lo, hi=hi, kinds=kinds, person_keys=person_keys, department_like=dept_key
            )
            fresh = await deps.freshness(db, "turnos")
        key = (lambda x: -x.days) if p.ordenar_por == "duracion" else (lambda x: x.start.toordinal())
        periods.sort(key=key)
        views = [_period_view(x, today, lo, hi) for x in periods]
        by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"personas": 0, "periodos": 0, "dias": 0})
        seen: dict[str, set[str]] = defaultdict(set)
        for x in periods:
            by_kind[x.kind]["periodos"] += 1
            by_kind[x.kind]["dias"] += x.days_within(lo, hi)
            seen[x.kind].add(x.person_key)
        for kind, people in seen.items():
            by_kind[kind]["personas"] = len(people)
        summary: dict[str, Any] = {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "resumen_por_tipo": dict(by_kind),
            "regla": "AUS-001: 'desde' y 'dias' son los del periodo real completo, no los de la consulta.",
            **fresh,
        }
        if len(views) <= MAX_ROWS_FOR_MODEL:
            summary["periodos"] = views
        else:
            summary["periodos_mas_relevantes"] = views[:MAX_ROWS_FOR_MODEL]
        rows = [
            [
                v["persona"],
                v["departamento"],
                v["tipo"],
                fmt_date(date.fromisoformat(v["desde"])),
                fmt_date(date.fromisoformat(v["hasta"])),
                v["dias"],
            ]
            for v in views
        ]
        state["foco_periodo"] = {"desde": lo.isoformat(), "hasta": hi.isoformat()}
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Ausencias", ["Persona", "Departamento", "Tipo", "Desde", "Hasta", "Días"], rows),
            state,
        )

    return Tool(
        "ausencias",
        "Ausencias (baja/IT, vacaciones, permisos, asuntos propios) según los turnos, con su periodo real "
        "completo: quién está de baja, desde cuándo, cuánto lleva, quién lleva más. Con una persona y sin "
        "fechas: su historial del año (número de bajas, días acumulados, última baja).",
        AusenciasParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ reincorporaciones (lista)
class ReincorporacionesParams(Periodo):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    tipos: list[str] | None = Field(default=None, description="Baja/IT, Vacaciones, Permiso, Asuntos propios")


def reincorporaciones(deps: Deps) -> Tool:
    async def handler(p: ReincorporacionesParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo, hi = p.resolve(today, default_days=14)
        kinds = tuple(
            k
            for k in ABSENCE_KINDS
            if not p.tipos or any(normalize_key(t) in normalize_key(k) for t in p.tipos)
        )
        async with deps.db.session() as db:
            dept_key = None
            if p.departamento:
                status, dept_key, options = await resolve_shift_department(db, p.departamento)
                if status is not ToolStatus.OK:
                    return department_not_found(status, p.departamento, options)
            periods = await absence_periods(db, lo=lo, hi=hi, kinds=kinds, department_like=dept_key)
            fresh = await deps.freshness(db, "turnos")
        published = [x for x in periods if x.return_shift is not None and lo <= x.return_shift.day <= hi]
        pending = [x for x in periods if x.return_shift is None and x.end <= hi]
        published.sort(key=lambda x: x.return_shift.day if x.return_shift else x.end)
        items = [
            {
                "persona": x.name,
                "departamento": x.department,
                "motivo": x.kind,
                "ausente_desde": x.start.isoformat(),
                "ausente_hasta": x.end.isoformat(),
                "vuelve": x.return_shift.day.isoformat() if x.return_shift else None,
                "turno": x.return_shift.raw_value if x.return_shift else None,
            }
            for x in published
        ]
        summary: dict[str, Any] = {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "con_reincorporacion_publicada": len(items),
            "personas_distintas": len({x.person_key for x in published}),
            "por_motivo": dict(Counter(x.kind for x in published)),
            "ausencia_termina_pero_sin_turno_publicado": len(pending),
            "regla": "VAC-001: reincorporación = primer turno de trabajo publicado tras la ausencia.",
            **fresh,
        }
        if len(items) <= MAX_ROWS_FOR_MODEL:
            summary["reincorporaciones"] = items
        rows = [[i["persona"], i["departamento"], i["motivo"], i["vuelve"], i["turno"]] for i in items]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Reincorporaciones", ["Persona", "Departamento", "Motivo", "Vuelve", "Turno"], rows),
            {"foco_periodo": {"desde": lo.isoformat(), "hasta": hi.isoformat()}},
        )

    return Tool(
        "reincorporaciones",
        "Lista de quién se reincorpora (con turno de trabajo publicado) en un periodo, por defecto los "
        "próximos 14 días, tras baja, vacaciones o permisos.",
        ReincorporacionesParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (turnos_persona, turnos_dia, ausencias, reincorporaciones):
        registry.register(factory(deps))
