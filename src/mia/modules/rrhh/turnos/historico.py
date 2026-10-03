"""Planificación v12: el histórico real de los calendarios de departamento (Calendario<Dept>_AAAA),
el catálogo de tipos de turno, las plantillas de generación y los comentarios de semana.

Distinto de ``turnos_persona``/``turnos_dia`` (que leen la lista Turnos, la proyección
semanal publicada): esto es la fuente histórica autoritativa, con horas reales.
Identifica a las personas por nombre, porque estas listas no llevan DNI.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import CalendarShift, ShiftDay, ShiftTemplate, ShiftTypeCatalog, WeekComment
from mia.ingestion.definitions import CALENDAR_DEPARTMENTS
from mia.modules.rrhh.common import Deps, Periodo, fmt_date, is_operational, table
from mia.text import normalize_key

WORKING_KINDS = ("work", "special")


def match_department(query: str | None) -> tuple[ToolStatus, str | None]:
    """Contra el conjunto fijo de departamentos de los calendarios (no cambia con la sincronización)."""
    if not (query or "").strip():
        return ToolStatus.OK, None
    wanted = normalize_key(query)
    exact = next((d for d in CALENDAR_DEPARTMENTS if normalize_key(d) == wanted), None)
    if exact:
        return ToolStatus.OK, exact
    partial = [d for d in CALENDAR_DEPARTMENTS if wanted in normalize_key(d)]
    return (ToolStatus.OK, partial[0]) if len(partial) == 1 else (ToolStatus.NOT_FOUND, None)


def department_options() -> list[str]:
    return list(CALENDAR_DEPARTMENTS)


# ------------------------------------------------------------------ histórico real
class HistoricoParams(Periodo):
    departamento: str = Field(description="Departamento (obligatorio: el calendario es por departamento)")
    empleado: str | None = Field(default=None, description="Nombre (o parte) de la persona")


def turnos_historico(deps: Deps) -> Tool:
    async def handler(p: HistoricoParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        status, department = match_department(p.departamento)
        if status is not ToolStatus.OK or department is None:
            return ToolResult(
                status,
                {
                    "mensaje": f"No existe el departamento «{p.departamento}» en los calendarios.",
                    "departamentos": department_options(),
                },
            )
        lo, hi = p.resolve(today, default_days=6)
        async with deps.db.session() as db:
            stmt = select(CalendarShift).where(
                CalendarShift.department == department, CalendarShift.day.between(lo, hi)
            )
            if p.empleado:
                tokens = normalize_key(p.empleado).split()
                for token in tokens:
                    stmt = stmt.where(CalendarShift.employee_name_key.like(f"%{token}%"))
            rows = list((await db.scalars(stmt.order_by(CalendarShift.day, CalendarShift.employee_name))).all())
        people = sorted({r.employee_name for r in rows if r.employee_name})
        if p.empleado and len(people) > 1:
            return ToolResult(ToolStatus.AMBIGUOUS, {"mensaje": "Hay varias personas que encajan", "personas": people})
        summary: dict[str, Any] = {
            "departamento": department,
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "regla": "Histórico real del Calendario, no la proyección publicada en Turnos.",
            "total_turnos": len(rows),
            "horas_totales": round(sum(r.hours_total or 0 for r in rows if r.kind in WORKING_KINDS), 1),
            "horas_nocturnas": round(sum(r.hours_night or 0 for r in rows if r.kind in WORKING_KINDS), 1),
        }
        if len(rows) <= 200:
            summary["turnos"] = [
                {
                    "fecha": fmt_date(r.day),
                    "persona": r.employee_name,
                    "descripcion": r.description,
                    "horas": r.hours_total,
                    "partido": r.split_shift,
                    "comentario": r.comment,
                }
                for r in rows
            ]
        rows_view = [[fmt_date(r.day), r.employee_name, r.description, r.hours_total, r.split_shift] for r in rows]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Histórico de turnos · {department}",
                ["Fecha", "Persona", "Descripción", "Horas", "Partido"],
                rows_view,
            ),
        )

    return Tool(
        "turnos_historico",
        "Histórico REAL de turnos de un departamento (Calendario), con horas y turnos partidos. Para la "
        "proyección semanal publicada usa turnos_persona/turnos_dia.",
        HistoricoParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ catálogo de tipos de turno
class CatalogoParams(BaseModel):
    departamento: str | None = None


def catalogo_tipos_turno(deps: Deps) -> Tool:
    async def handler(p: CatalogoParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(ShiftTypeCatalog)
            if p.departamento:
                stmt = stmt.where(ShiftTypeCatalog.department_key.like(f"%{normalize_key(p.departamento)}%"))
            rows = list((await db.scalars(stmt.order_by(ShiftTypeCatalog.department, ShiftTypeCatalog.code))).all())
        items = [
            {
                "tipo": r.code,
                "departamento": r.department,
                "descripcion": r.description,
                "horario": f"{r.start1}-{r.end1}" + (f" / {r.start2}-{r.end2}" if r.split_shift else ""),
                "horas": r.hours_total,
                "horas_nocturnas": r.hours_night,
            }
            for r in rows
        ]
        return ToolResult(
            ToolStatus.OK,
            {"total": len(items), "tipos": items},
            table(
                "Tipos de turno (TipoTurnos)",
                ["Tipo", "Departamento", "Descripción", "Horario", "Horas"],
                [[i["tipo"], i["departamento"], i["descripcion"], i["horario"], i["horas"]] for i in items],
            ),
        )

    return Tool(
        "catalogo_tipos_turno",
        "Catálogo de tipos de turno (TipoTurnos): horarios y horas definidas por departamento.",
        CatalogoParams,
        handler,
        permission=Permission.TURNOS_LEER,
    )


# ------------------------------------------------------------------ plantillas de generación
class PlantillasParams(BaseModel):
    departamento: str | None = None
    empleado: str | None = None


def plantillas_turno(deps: Deps) -> Tool:
    async def handler(p: PlantillasParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(ShiftTemplate)
            if p.departamento:
                stmt = stmt.where(ShiftTemplate.department_key.like(f"%{normalize_key(p.departamento)}%"))
            if p.empleado:
                stmt = stmt.where(ShiftTemplate.employee_name_key.like(f"%{normalize_key(p.empleado)}%"))
            rows = list((await db.scalars(stmt.order_by(ShiftTemplate.template_start))).all())
        items = [
            {
                "persona": r.employee_name,
                "departamento": r.department,
                "desde": fmt_date(r.template_start),
                "hasta": fmt_date(r.template_end),
                "horario": r.schedule,
                "comentario": r.comment,
            }
            for r in rows
        ]
        return ToolResult(
            ToolStatus.OK,
            {
                "total": len(items),
                "plantillas": items,
                "regla": "Son reglas de generación de turnos, no histórico real: el Calendario es la fuente real.",
            },
            table(
                "Plantillas de turno",
                ["Persona", "Departamento", "Desde", "Hasta"],
                [[i["persona"], i["departamento"], i["desde"], i["hasta"]] for i in items],
            ),
        )

    return Tool(
        "plantillas_turno",
        "Plantillas de generación de turnos (TurnosPlantillas): reglas L-D por persona, no el histórico real.",
        PlantillasParams,
        handler,
        permission=Permission.TURNOS_LEER,
    )


# ------------------------------------------------------------------ comentarios de semana
class ComentariosParams(BaseModel):
    departamento: str
    anio: int | None = None
    semana: int | None = None


def comentarios_semana_turno(deps: Deps) -> Tool:
    async def handler(p: ComentariosParams, ctx: ToolContext) -> ToolResult:
        iso = ctx.now.isocalendar()
        year, week = p.anio or iso.year, p.semana or iso.week
        async with deps.db.session() as db:
            row = await db.scalar(
                select(WeekComment).where(
                    WeekComment.department_key.like(f"%{normalize_key(p.departamento)}%"),
                    WeekComment.year == year,
                    WeekComment.week == week,
                )
            )
        if row is None:
            return ToolResult(
                ToolStatus.NOT_FOUND, f"No hay comentario de semana para {p.departamento} ({year}-W{week:02d})."
            )
        return ToolResult(
            ToolStatus.OK,
            {
                "departamento": row.department,
                "anio": year,
                "semana": week,
                "comentario_principal": row.main_comment,
                "comentarios_por_dia": row.day_comments,
                "regla": "Comentario de departamento/semana; nunca se atribuye a una persona (es distinto del "
                "comentario de un turno individual).",
            },
        )

    return Tool(
        "comentarios_semana_turno",
        "Comentario de contexto de un departamento en una semana (ComentariosTurnosSemanas); no es de una persona.",
        ComentariosParams,
        handler,
        permission=Permission.TURNOS_LEER,
    )


# ------------------------------------------------------------------ métricas
class MetricasParams(Periodo):
    departamento: str = Field(description="Departamento (el calendario es por departamento)")
    empleado: str | None = Field(default=None, description="Nombre de una persona: sus horas y jornadas del periodo")


def metricas_turnos(deps: Deps) -> Tool:
    async def handler(p: MetricasParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        status, department = match_department(p.departamento)
        if status is not ToolStatus.OK or department is None:
            return ToolResult(
                status,
                {"mensaje": f"No existe el departamento «{p.departamento}».", "departamentos": department_options()},
            )
        lo, hi = p.resolve(today.replace(day=1), default_days=0)
        if not p.desde and not p.hasta:
            hi = today
        async with deps.db.session() as db:
            rows = list(
                (
                    await db.scalars(
                        select(CalendarShift).where(
                            CalendarShift.department == department, CalendarShift.day.between(lo, hi)
                        )
                    )
                ).all()
            )
        if p.empleado:
            tokens = normalize_key(p.empleado).split()
            rows = [r for r in rows if all(t in (r.employee_name_key or "") for t in tokens)]
            people = {r.employee_name for r in rows if r.employee_name}
            if len(people) > 1:
                return ToolResult(
                    ToolStatus.AMBIGUOUS, {"mensaje": "Hay varias personas que encajan", "personas": sorted(people)}
                )
        working = [r for r in rows if r.kind in WORKING_KINDS]
        by_person: dict[str, dict[str, float]] = defaultdict(lambda: {"jornadas": 0, "horas": 0.0, "nocturnas": 0.0})
        for r in working:
            key = r.employee_name or "Sin nombre"
            by_person[key]["jornadas"] += 1
            by_person[key]["horas"] += r.hours_total or 0
            by_person[key]["nocturnas"] += r.hours_night or 0
        summary = {
            "departamento": department,
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "jornadas_trabajadas": len(working),
            "horas_totales": round(sum(r.hours_total or 0 for r in working), 1),
            "horas_nocturnas": round(sum(r.hours_night or 0 for r in working), 1),
            "turnos_partidos": sum(1 for r in working if r.split_shift),
            "por_estado": dict(Counter(r.kind for r in rows)),
            "regla": "OFF, sin asignación y turnos de 0 horas no cuentan como jornada trabajada.",
        }
        rows_view = [
            [p_, round(v["jornadas"]), round(v["horas"], 1), round(v["nocturnas"], 1)]
            for p_, v in sorted(by_person.items(), key=lambda kv: -kv[1]["horas"])
        ]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Métricas de turnos · {department}", ["Persona", "Jornadas", "Horas", "Nocturnas"], rows_view),
        )

    return Tool(
        "metricas_turnos",
        "Jornadas, horas y horas nocturnas reales de un departamento en un periodo, por persona (a partir del "
        "Calendario); con empleado, las horas de una persona concreta.",
        MetricasParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ auditoría de publicación
class AuditoriaParams(BaseModel):
    departamento: str
    fecha: date | None = None


def auditoria_publicacion(deps: Deps) -> Tool:
    async def handler(p: AuditoriaParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        status, department = match_department(p.departamento)
        if status is not ToolStatus.OK or department is None:
            return ToolResult(
                status,
                {"mensaje": f"No existe el departamento «{p.departamento}».", "departamentos": department_options()},
            )
        day = p.fecha or today
        async with deps.db.session() as db:
            published = list(
                (
                    await db.scalars(
                        select(ShiftDay).where(
                            ShiftDay.department_key == normalize_key(department), ShiftDay.day == day
                        )
                    )
                ).all()
            )
            real = list(
                (
                    await db.scalars(
                        select(CalendarShift).where(CalendarShift.department == department, CalendarShift.day == day)
                    )
                ).all()
            )
        by_pub = {normalize_key(s.employee_name): s for s in published if s.employee_name}
        by_real = {r.employee_name_key: r for r in real if r.employee_name_key}
        mismatches = []
        for key in sorted(set(by_pub) | set(by_real)):
            pub, rea = by_pub.get(key), by_real.get(key)
            if pub is None:
                mismatches.append(
                    {
                        "persona": rea.employee_name if rea else key,
                        "problema": "en el Calendario pero sin turno publicado en Turnos",
                    }
                )
            elif rea is None:
                mismatches.append(
                    {
                        "persona": pub.employee_name,
                        "problema": "publicado en Turnos sin turno real en el Calendario ese día",
                    }
                )
        return ToolResult(
            ToolStatus.OK,
            {
                "departamento": department,
                "fecha": day.isoformat(),
                "en_turnos_publicado": len(published),
                "en_calendario_real": len(real),
                "discrepancias": len(mismatches),
                "detalle": mismatches[:60],
                "regla": "Calendario = planificación/histórico autoritativo; Turnos = proyección publicada visible.",
            },
        )

    return Tool(
        "auditoria_publicacion_turnos",
        "Compara lo publicado en Turnos con el histórico real del "
        "Calendario para un día: quién no coincide entre ambos.",
        AuditoriaParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


# ------------------------------------------------------------------ disponibilidad cruzada (2D3B10)
class DisponibilidadParams(BaseModel):
    departamento: str
    fecha: date | None = None


def disponibilidad_dia(deps: Deps) -> Tool:
    """Plantilla activa + Calendario + vacaciones aceptadas + ETT del día, como el sistema anterior.

    Plantilla y ETT son poblaciones separadas y los conflictos no se corrigen: se señalan.
    """

    async def handler(p: DisponibilidadParams, ctx: ToolContext) -> ToolResult:
        from mia.data import Employee, TtTimesheet, TtWorker, Vacation  # noqa: PLC0415

        status, department = match_department(p.departamento)
        if status is not ToolStatus.OK or department is None:
            return ToolResult(
                status,
                {"mensaje": f"No existe el departamento «{p.departamento}».", "departamentos": department_options()},
            )
        day = p.fecha or ctx.now.date()
        key = normalize_key(department)
        async with deps.db.session() as db:
            staff = list(
                (
                    await db.scalars(select(Employee).where(Employee.active.is_(True), Employee.department_key == key))
                ).all()
            )
            planned = list(
                (
                    await db.scalars(
                        select(CalendarShift).where(CalendarShift.department == department, CalendarShift.day == day)
                    )
                ).all()
            )
            vacations = list(
                (await db.scalars(select(Vacation).where(Vacation.start_date <= day, Vacation.end_date >= day))).all()
            )
            ett_rows = list(
                (
                    await db.scalars(
                        select(TtTimesheet).where(TtTimesheet.day == day, TtTimesheet.department_key.like(f"%{key}%"))
                    )
                ).all()
            )
            ett_visible = {
                normalize_key(w.name)
                for w in (await db.scalars(select(TtWorker).where(TtWorker.visible.is_(True)))).all()
            }
        on_vacation = {v.employee_email for v in vacations if is_operational(v.status)}
        plan_by_name = {r.employee_name_key: r for r in planned if r.employee_name_key}
        working: list[str] = []
        off: list[str] = []
        sick: list[str] = []
        unplanned: list[str] = []
        alerts: list[dict[str, str]] = []
        for e in staff:
            entry = plan_by_name.get(normalize_key(e.name))
            vacation = e.email in on_vacation
            if entry is None:
                (off if vacation else unplanned).append(e.name)
                continue
            if "baja" in normalize_key(entry.description):
                sick.append(e.name)
            elif entry.kind in WORKING_KINDS:
                working.append(e.name)
                if vacation:
                    alerts.append({"persona": e.name, "alerta": "planificada para trabajar con vacaciones aceptadas"})
            else:
                off.append(e.name)
        ett = sorted({r.worker_name for r in ett_rows if r.worker_name})
        summary = {
            "departamento": department,
            "fecha": day.isoformat(),
            "plantilla_activa": len(staff),
            "trabajan": len(working),
            "libran_o_vacaciones": len(off),
            "baja_it": len(sick),
            "sin_planificar": len(unplanned),
            "ett_con_boletin": len(ett),
            "ett_no_visibles": [n for n in ett if normalize_key(n) not in ett_visible],
            "alertas": alerts,
            "detalle": {"trabajan": working, "baja_it": sick, "sin_planificar": unplanned, "ett": ett},
            "regla": "Plantilla y ETT son poblaciones separadas; los conflictos se señalan, no se corrigen.",
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Disponibilidad · {department} · {fmt_date(day)}",
                ["Situación", "Personas"],
                [
                    ["Trabajan", len(working)],
                    ["Libran o vacaciones", len(off)],
                    ["Baja/IT", len(sick)],
                    ["Sin planificar", len(unplanned)],
                    ["ETT con boletín", len(ett)],
                ],
            ),
        )

    return Tool(
        "disponibilidad_dia",
        "Disponibilidad real de un departamento un día: quién trabaja, libra, está de "
        "baja o sin planificar según el Calendario, cruzado con vacaciones aceptadas y con el personal ETT.",
        DisponibilidadParams,
        handler,
        permission=Permission.TURNOS_LEER,
        audit_resource="turnos",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (
        turnos_historico,
        catalogo_tipos_turno,
        plantillas_turno,
        comentarios_semana_turno,
        metricas_turnos,
        auditoria_publicacion,
        disponibilidad_dia,
    ):
        registry.register(factory(deps))
