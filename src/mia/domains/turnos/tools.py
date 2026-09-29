"""Turnos: el día a día de cada persona y de la plantilla, ausencias y reincorporaciones."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, ShiftDay
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    ActivosParams,
    CohortParams,
    Deps,
    PeopleDirectory,
    Periodo,
    PersonaParams,
    active_person_keys,
    days_between,
    employees_for,
    fmt_date,
    focus_person,
    no_population,
    person_problem,
    population_label,
    population_state,
    previous_population,
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

# TUR-001: franjas por hora de INICIO del turno. Misma definición que el ejecutor v12 del sistema
# anterior (el que usaban de verdad): mañana 06:00-13:59, tarde 14:00-21:59, noche 22:00-05:59.
FRANJAS: dict[str, tuple[int, int]] = {
    "mañana": (6 * 60, 14 * 60),
    "tarde": (14 * 60, 22 * 60),
    "noche": (22 * 60, 6 * 60),
}
Franja = Literal["mañana", "tarde", "noche"]


_TOMORROW = re.compile(r"\btrabaj\w*\s+(?:el\s+d[ií]a\s+de\s+)?ma[nñ]ana\b", re.IGNORECASE)
_MORNING = re.compile(
    r"turno\s+de\s+ma[nñ]ana|por\s+la\s+ma[nñ]ana|de\s+ma[nñ]ana\s+(?:de\s+)?(?:hoy|el)", re.IGNORECASE
)


def tomorrow_not_morning(message: str, franja: str | None, fecha: date | None, today: date) -> bool:
    """«¿Quién trabaja mañana?» = el día siguiente (con franja «mañana» o sin franja y sin fecha)."""
    return (
        franja in ("mañana", None)
        and fecha in (None, today)
        and bool(_TOMORROW.search(message or ""))
        and not _MORNING.search(message or "")
    )


_WORKING = re.compile(r"\btrabaj|\bqui[eé]n(?:es)?\s+(?:est[aá]n?|hay)\s+(?:de\s+)?turno", re.IGNORECASE)


async def _shifts_of_day(
    db: AsyncSession, day: date, dept_key: str | None, *, include_inactive: bool
) -> list[ShiftDay]:
    """Turnos publicados de un día; por defecto solo de la plantilla activa (POB-001)."""
    stmt = select(ShiftDay).where(ShiftDay.day == day)
    if not include_inactive:
        stmt = stmt.where(ShiftDay.person_key.in_(active_person_keys()))
    if dept_key:
        stmt = stmt.where(ShiftDay.department_key == dept_key)
    return list((await db.scalars(stmt.order_by(ShiftDay.department, ShiftDay.employee_name))).all())


def _day_rows(selected: list[ShiftDay], directory: PeopleDirectory, summary: dict[str, Any]) -> list[list[Any]]:
    """Filas de los turnos del día cruzadas con la ficha del empleado (puesto)."""
    for person in summary.get("personas", []):
        match = next((s for s in selected if s.employee_name == person["nombre"]), None)
        person["puesto"] = directory.puesto(person_key=match.person_key) if match else None
    return [
        [
            s.employee_name,
            directory.puesto(person_key=s.person_key),
            s.department,
            s.kind,
            s.raw_value,
            s.area,
            s.comment,
        ]
        for s in selected
    ]


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
    """TUR-002: presencia por solape de cada tramo (un 22:00-06:00 cubre las 02:00; un turno
    partido 10-14 / 18-22 no cubre las 16:00)."""
    tramos = [t.split("-") for t in (shift.segments or "").split(",") if "-" in t]
    if not tramos and shift.start_time and shift.end_time:
        tramos = [[shift.start_time, shift.end_time]]
    for a, b in tramos:
        start, end = _minutes(a), _minutes(b)
        if start is None or end is None:
            continue
        if end <= start:
            end += 24 * 60
        if start <= minute < end or start <= minute + 24 * 60 < end:
            return True
    return False


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


async def resolve_shift_department(db: AsyncSession, query: str | None) -> tuple[ToolStatus, str | None, list[str]]:
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
    verb = "Hay varios departamentos que encajan" if status is ToolStatus.AMBIGUOUS else "No existe ese departamento"
    return ToolResult(status, {"mensaje": f"{verb} («{query}»). No es que no haya turnos.", "departamentos": options})


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
class TurnosDiaParams(CohortParams, ActivosParams):
    fecha: date | None = Field(default=None, description="Día AAAA-MM-DD (por defecto hoy)")
    departamento: str | None = Field(default=None, description="Departamento (opcional; sin él, toda la plantilla)")
    franja: Franja | None = Field(
        default=None,
        description="Turno de mañana (empieza 06:00-13:59), tarde (14:00-21:59) o noche (22:00-05:59)",
    )
    empieza_a: str | None = Field(default=None, description="HH:MM: quién entra exactamente a esa hora")
    hora: str | None = Field(
        default=None, description="HH:MM para saber quién está trabajando a esa hora (presencia, no inicio)"
    )
    tipo: str | None = Field(default=None, description="Trabajo, Descanso, Vacaciones, Baja/IT… (por defecto todos)")


def turnos_dia(deps: Deps) -> Tool:
    async def handler(p: TurnosDiaParams, ctx: ToolContext) -> ToolResult:
        day = p.fecha or ctx.now.date()
        note = None
        if tomorrow_not_morning(ctx.user_message, p.franja, p.fecha, ctx.now.date()):
            # «¿Quién trabaja mañana?» es el día siguiente, no el turno de mañana (fallo real repetido).
            day, p.franja = ctx.now.date() + timedelta(days=1), None
            note = "Interpretado como el día de mañana (no como el turno de mañana)."
        async with deps.db.session() as db:
            status, dept_key, options = await resolve_shift_department(db, p.departamento)
            if status is not ToolStatus.OK:
                return department_not_found(status, p.departamento, options)
            shifts = await _shifts_of_day(db, day, dept_key, include_inactive=p.incluir_inactivos)
            fresh = await deps.freshness(db, "turnos")
        if not shifts:
            scope = f"en {p.departamento}" if p.departamento else "en ninguna parte de la plantilla"
            return ToolResult(
                ToolStatus.NOT_FOUND,
                {"mensaje": f"No hay turnos publicados el {fmt_date(day)} {scope}.", **fresh},
            )
        selected = shifts
        criteria = []
        if p.sobre_resultado_anterior or p.resultado:
            if (previous := previous_population(ctx, p.resultado)) is None:
                return no_population()
            keys = set(previous["person_keys"])
            selected = [s for s in selected if s.person_key in keys]
            criteria.append(f"de: {previous['etiqueta']}")
        if p.tipo:
            wanted = normalize_key(p.tipo)
            selected = [s for s in selected if wanted in normalize_key(s.kind)]
            criteria.append(f"tipo {p.tipo}")
        if p.franja:
            selected = [s for s in selected if s.kind == ShiftKind.TRABAJO and starts_in(s, p.franja)]
            criteria.append(f"turno de {p.franja} (por hora de inicio)")
        if p.empieza_a and (start := _minutes(p.empieza_a)) is not None:
            selected = [s for s in selected if s.kind == ShiftKind.TRABAJO and _minutes(s.start_time) == start]
            criteria.append(f"entra a las {p.empieza_a}")
        if p.hora and (minute := _minutes(p.hora)) is not None:
            selected = [s for s in selected if s.kind == ShiftKind.TRABAJO and works_at(s, minute)]
            criteria.append(f"trabajando a las {p.hora}")
        working = [s for s in shifts if s.kind == ShiftKind.TRABAJO]
        if not criteria and _WORKING.search(ctx.user_message or ""):
            # «¿Quién trabaja…?» son los turnos de Trabajo, no todos los del día (fallo real: 280 en vez de 128).
            selected = [s for s in selected if s.kind == ShiftKind.TRABAJO]
            criteria.append("trabajando")
        summary: dict[str, Any] = {
            "fecha": day.isoformat(),
            "departamento": shifts[0].department if dept_key else "toda la plantilla",
            "criterio": ", ".join(criteria) or "todos los turnos del día",
            **({"nota": note} if note else {}),
            "poblacion": population_label(p.incluir_inactivos),
            "total_seleccionado": len(selected),
            "personas_trabajando_ese_dia": len(working),
            "horas_seleccionadas": round(sum(s.hours or 0 for s in selected), 1),
            "seleccion_por_departamento": dict(Counter(s.department or "Sin dato" for s in selected).most_common()),
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
        state: dict[str, Any] = {"foco_periodo": {"desde": day.isoformat()}}
        async with deps.db.session() as db:
            people = await employees_for(db, person_keys={s.person_key for s in selected if s.person_key})
        rows = _day_rows(selected, PeopleDirectory(people), summary)
        state.update(population_state(f"turnos {day.isoformat()} ({summary['criterio']})", people))
        if dept_key:
            state["foco_departamento"] = shifts[0].department
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Turnos {fmt_date(day)}",
                ["Persona", "Puesto", "Departamento", "Tipo", "Turno", "Área", "Comentario"],
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
def _period_view(
    p: AbsencePeriod, today: date, lo: date, hi: date, directory: PeopleDirectory | None = None
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "persona": p.name,
        "puesto": directory.puesto(person_key=p.person_key) if directory else None,
        "departamento": p.department,
        "tipo": p.kind,
        "desde": p.start.isoformat(),
        "hasta": p.end.isoformat(),
        "dias_totales_publicados": p.days,
        "dias_en_el_periodo_consultado": p.days_within(lo, hi),
        "en_curso": p.start <= today <= p.end,
    }
    if p.start <= today:
        view["dias_hasta_hoy"] = (min(p.end, today) - p.start).days + 1
    if p.starts_before_data:
        view["nota"] = "empezó antes del histórico disponible: puede ser más larga"
    if p.return_shift is not None:
        view["vuelve"] = {"fecha": p.return_shift.day.isoformat(), "turno": p.return_shift.raw_value}
    return view


class AusenciasParams(Periodo, CohortParams, ActivosParams):
    empleado_id: int | None = Field(default=None, description="Persona concreta (del foco o de una búsqueda)")
    nombre: str | None = Field(default=None, description="Nombre de la persona, si no hay empleado_id")
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    tipos: list[str] | None = Field(
        default=None, description="Baja/IT, Vacaciones, Permiso, Asuntos propios (por defecto todos)"
    )
    ordenar_por: Literal["duracion", "inicio"] = Field(default="duracion", description="Por defecto, las más largas")


def _absence_summary(
    periods: list[AbsencePeriod], today: date, lo: date, hi: date, directory: PeopleDirectory | None = None
) -> tuple[dict[str, Any], list[list[Any]]]:
    views = [_period_view(x, today, lo, hi, directory) for x in periods]
    by_kind: dict[str, dict[str, float]] = defaultdict(
        lambda: {"personas": 0, "periodos": 0, "dias": 0, "_dias_completos": 0}
    )
    seen: dict[str, set[str]] = defaultdict(set)
    for x in periods:
        by_kind[x.kind]["periodos"] += 1
        by_kind[x.kind]["dias"] += x.days_within(lo, hi)
        by_kind[x.kind]["_dias_completos"] += x.days
        seen[x.kind].add(x.person_key)
    for kind, keys in seen.items():
        by_kind[kind]["personas"] = len(keys)
    for stats in by_kind.values():
        # Duración media = duración COMPLETA de cada periodo / número de periodos. Con los días dentro de la
        # ventana, preguntar por «hoy» daba 1 día de media (fallo real del modo sombra).
        full = stats.pop("_dias_completos", 0)
        stats["duracion_media_dias"] = round(full / stats["periodos"], 2) if stats["periodos"] else 0
    dept_kind: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for x in periods:
        dept_kind[x.department or "Sin dato"][x.kind].add(x.person_key)
    dept_people: dict[str, set[str]] = defaultdict(set)
    for x in periods:
        dept_people[x.department or "Sin dato"].add(x.person_key)
    summary: dict[str, Any] = {
        "desde": lo.isoformat(),
        "hasta": hi.isoformat(),
        "resumen_por_tipo": dict(by_kind),
        "personas_por_departamento": dict(sorted(((d, len(k)) for d, k in dept_people.items()), key=lambda kv: -kv[1])),
        "personas_por_departamento_y_tipo": {
            d: {k: len(v) for k, v in kinds.items()} for d, kinds in sorted(dept_kind.items())
        },
        "regla": (
            "AUS-001: 'desde' es el inicio real del periodo. 'dias_hasta_hoy' = cuánto lleva; "
            "'dias_totales_publicados' incluye días futuros ya publicados."
        ),
    }
    key = "periodos" if len(views) <= MAX_ROWS_FOR_MODEL else "periodos_mas_relevantes"
    summary[key] = views[:MAX_ROWS_FOR_MODEL]
    rows = [
        [
            v["persona"],
            v["puesto"],
            v["departamento"],
            v["tipo"],
            fmt_date(date.fromisoformat(v["desde"])),
            fmt_date(date.fromisoformat(v["hasta"])),
            v["dias_totales_publicados"],
        ]
        for v in views
    ]
    return summary, rows


def _last_sick_leave(periods: list[AbsencePeriod], today: date) -> dict[str, Any]:
    last = max((x for x in periods if x.kind == ShiftKind.BAJA), key=lambda x: x.start, default=None)
    return {
        "ultima_baja_it": (
            {
                "desde": last.start.isoformat(),
                "hasta": last.end.isoformat(),
                "en_curso": last.start <= today <= last.end,
            }
            if last
            else "ninguna en el periodo consultado"
        ),
        "nota_bajas": "«Baja» es solo Baja/IT: unas vacaciones o un permiso no son una baja.",
    }


def ausencias(deps: Deps) -> Tool:
    async def handler(p: AusenciasParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        kinds = tuple(
            k for k in ABSENCE_KINDS if not p.tipos or any(normalize_key(t) in normalize_key(k) for t in p.tipos)
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
            if p.sobre_resultado_anterior or (p.resultado and person_keys is None):
                if (previous := previous_population(ctx, p.resultado)) is None:
                    return no_population()
                person_keys = list(previous["person_keys"])
            periods = await absence_periods(
                db,
                lo=lo,
                hi=hi,
                kinds=kinds,
                person_keys=person_keys,
                department_like=dept_key,
                only_active=person_keys is None and not p.incluir_inactivos,
            )
            people = await employees_for(db, person_keys={x.person_key for x in periods})
            fresh = await deps.freshness(db, "turnos")
        key = (lambda x: -x.days) if p.ordenar_por == "duracion" else (lambda x: x.start.toordinal())
        periods.sort(key=key)
        async with deps.db.session() as db:
            directory = await PeopleDirectory.load(db, person_keys={x.person_key for x in periods})
        summary, rows = _absence_summary(periods, today, lo, hi, directory)
        summary.update(fresh)
        if person_keys is None or p.sobre_resultado_anterior:
            summary["poblacion"] = population_label(p.incluir_inactivos)
        state["foco_periodo"] = {"desde": lo.isoformat(), "hasta": hi.isoformat()}
        if person_keys and len(person_keys) == 1:
            summary.update(_last_sick_leave(periods, today))
        elif periods and p.ordenar_por == "duracion":
            # «¿quién lleva más?» → la siguiente pregunta («desde cuándo») se refiere a esa persona.
            top = await _employee_by_key(deps, periods[0].person_key)
            if top is not None:
                state.update(focus_person(top))
                summary["persona_destacada"] = {"nombre": top.name, "empleado_id": top.sp_id}
        if person_keys is None or p.sobre_resultado_anterior:
            state.update(population_state(f"ausencias {lo.isoformat()}–{hi.isoformat()}", people))
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Ausencias", ["Persona", "Puesto", "Departamento", "Tipo", "Desde", "Hasta", "Días"], rows),
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
def _multi_kind(periods: list[AbsencePeriod]) -> list[dict[str, Any]]:
    kinds: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str | None] = {}
    for x in periods:
        kinds[x.person_key].add(x.kind)
        names[x.person_key] = x.name
    return [{"persona": names[k], "motivos": sorted(v)} for k, v in kinds.items() if len(v) > 1]


class ReincorporacionesParams(Periodo, CohortParams, ActivosParams):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    empleado_ids: list[int] | None = Field(
        default=None, description="Limitar a estas personas (ids del foco o de una búsqueda)"
    )
    tipos: list[str] | None = Field(
        default=None,
        description="Limitar a uno o varios motivos: Baja/IT, Vacaciones, Permiso, Asuntos propios. Por defecto, todos",
    )


def reincorporaciones(deps: Deps) -> Tool:
    async def handler(p: ReincorporacionesParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo, hi = p.resolve(today, default_days=35)  # como el sistema anterior: próximos 35 días
        kinds = (
            tuple(k for k in ABSENCE_KINDS if any(normalize_key(t) in normalize_key(k) for t in p.tipos))
            if p.tipos
            else ABSENCE_KINDS  # REI-001: la reincorporación es tras cualquiera de los cuatro motivos
        )
        async with deps.db.session() as db:
            dept_key = None
            if p.departamento:
                status, dept_key, options = await resolve_shift_department(db, p.departamento)
                if status is not ToolStatus.OK:
                    return department_not_found(status, p.departamento, options)
            person_keys = None
            if p.empleado_ids:
                keys = await db.scalars(select(Employee.person_key).where(Employee.sp_id.in_(p.empleado_ids)))
                person_keys = [k for k in keys.all() if k]
            elif p.sobre_resultado_anterior or p.resultado:
                if (previous := previous_population(ctx, p.resultado)) is None:
                    return no_population()
                person_keys = list(previous["person_keys"])
            periods = await absence_periods(
                db,
                lo=lo,
                hi=hi,
                kinds=kinds,
                department_like=dept_key,
                person_keys=person_keys,
                only_active=person_keys is None and not p.incluir_inactivos,
            )
            fresh = await deps.freshness(db, "turnos")
            published = [x for x in periods if x.return_shift is not None and lo <= x.return_shift.day <= hi]
            people = await employees_for(db, person_keys={x.person_key for x in published})
        pending = [x for x in periods if x.return_shift is None and x.end <= hi]
        published.sort(key=lambda x: x.return_shift.day if x.return_shift else x.end)
        async with deps.db.session() as db:
            directory = await PeopleDirectory.load(db, person_keys={x.person_key for x in published})
        items = [
            {
                "persona": x.name,
                "puesto": directory.puesto(person_key=x.person_key),
                "departamento": x.department,
                "motivo": x.kind,
                "tras": f"tras {x.kind.lower()}",
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
            "poblacion": population_label(p.incluir_inactivos),
            "con_reincorporacion_publicada": len(items),
            "personas_distintas": len({x.person_key for x in published}),
            "por_motivo": dict(Counter(x.kind for x in published)),
            "personas_con_mas_de_un_motivo": _multi_kind(published),
            "por_departamento_y_motivo": {
                d: dict(Counter(x.kind for x in published if (x.department or "Sin dato") == d))
                for d in sorted({x.department or "Sin dato" for x in published})
            },
            "ausencia_termina_pero_sin_turno_publicado": len(pending),
            "regla": "VAC-001: reincorporación = primer turno de trabajo publicado tras la ausencia.",
            **fresh,
        }
        if len(items) <= MAX_ROWS_FOR_MODEL:
            summary["reincorporaciones"] = items
        rows = [[i["persona"], i["puesto"], i["departamento"], i["motivo"], i["vuelve"], i["turno"]] for i in items]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Reincorporaciones", ["Persona", "Puesto", "Departamento", "Vuelve tras", "Vuelve", "Turno"], rows),
            {
                "foco_periodo": {"desde": lo.isoformat(), "hasta": hi.isoformat()},
                **population_state(f"reincorporaciones {lo.isoformat()}–{hi.isoformat()}", people),
            },
        )

    return Tool(
        "reincorporaciones",
        "Lista de quién se reincorpora (con turno de trabajo publicado) en un periodo, por defecto los "
        "próximos 35 días, tras baja, permiso, vacaciones o asuntos propios, indicando tras cuál vuelve cada una.",
        ReincorporacionesParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


async def _employee_by_key(deps: Deps, person_key: str) -> Employee | None:
    async with deps.db.session() as db:
        people = await employees_for(db, person_keys={person_key})
    return people[0] if people else None


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (turnos_persona, turnos_dia, ausencias, reincorporaciones):
        registry.register(factory(deps))
