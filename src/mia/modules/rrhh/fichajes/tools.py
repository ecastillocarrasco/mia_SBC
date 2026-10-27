"""Fichajes (control de presencia): marcas de entrada/salida importadas de Conectia y su cruce
con los turnos planificados.

Fuente actual: importación manual del Excel de Conectia — solo entornos de prueba (ver
``mia.modules.rrhh.fichajes.importer``). Cuando exista la API real de Conectia
(``mia.connectors.a3.TimeClockConnector``), estas herramientas siguen funcionando igual: leen
``ClockMark``, no el origen de los datos.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import ClockMark, Employee, ShiftDay
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import (
    Deps,
    PersonaParams,
    department_problem,
    fmt_date,
    focus_person,
    person_problem,
    resolve_department,
    resolve_person,
    table,
)
from mia.modules.rrhh.fichajes.comparison import DayComparison, ShiftExpectation, compare_person
from mia.modules.rrhh.fichajes.pairing import pair_marks

KEYWORDS = (
    "fichaje",
    "fichajes",
    "fichar",
    "fichado",
    "fichada",
    "fichó",
    "ficho",
    "fichan",
    "marcaje",
    "marcajes",
    "marcar entrada",
    "marcar salida",
    "sin turno asignado",
    "control de presencia",
    "control horario",
    "conectia",
    "reloj de fichar",
    "compara los turnos con los fichajes",
    "horas fichadas",
    "marcajes incorrectos",
    "faltas de marcaje",
    "desviacion de fichaje",
    "desviación de fichaje",
)
"""Ver `empleados.tools.KEYWORDS` para el criterio."""

DEFAULT_TOLERANCE_MIN = 15
MADRID = ZoneInfo("Europe/Madrid")
"""Fichajes/turnos son siempre hora local de Sunset Beach Club (Málaga) — ``ClockMark.at`` se
escribe con esta zona (``importer.py``), pero PostgreSQL la devuelve con tzinfo UTC al leerla (un
TIMESTAMPTZ representa un instante, no una zona): hay que relocalizar explícitamente antes de
mostrar u operar con la hora local, nunca asumir que el tzinfo que trae la fila ya es el correcto
(bug real encontrado contra datos de producción, 2026-10-21 — las horas de fichaje se mostraban
1-2h por detrás de la hora real)."""


class PersonaPeriodoParams(PersonaParams):
    desde: date | None = Field(default=None, description="Inicio del periodo (por defecto, lunes de esta semana)")
    hasta: date | None = Field(default=None, description="Fin del periodo (por defecto, hoy)")


class ComparacionParams(BaseModel):
    empleado_id: int | None = Field(
        default=None, description="Limitar a una persona (ID del foco o de una búsqueda previa)"
    )
    nombre: str | None = Field(default=None, description="Limitar a una persona por nombre, si no hay empleado_id")
    departamento: str | None = Field(
        default=None,
        description="Limitar a un departamento; sin persona ni departamento, toda la plantilla con turno o fichaje en el periodo",
    )
    desde: date | None = Field(default=None, description="Inicio del periodo (por defecto, lunes de esta semana)")
    hasta: date | None = Field(default=None, description="Fin del periodo (por defecto, hoy)")
    tolerancia_minutos: int = Field(
        default=DEFAULT_TOLERANCE_MIN,
        description="Margen en minutos para considerar un fichaje 'correcto' frente al turno programado",
    )


def _week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _day_bounds(lo: date, hi: date) -> tuple[datetime, datetime]:
    return datetime.combine(lo, time.min, tzinfo=MADRID), datetime.combine(
        hi + timedelta(days=1), time.min, tzinfo=MADRID
    )


def _localize_marks(marks: list[datetime]) -> list[datetime]:
    """Ver ``MADRID``: PostgreSQL devuelve ``ClockMark.at`` con tzinfo UTC, nunca Europe/Madrid,
    aunque se escribió con la hora local correcta — relocaliza aquí, el único punto donde se leen
    las marcas, antes de que lleguen a ``pairing``/``comparison`` (que sí asumen hora local de
    Madrid). Función pura y separada a propósito para poder probarla sin depender de que SQLite
    (solo tests) conserve o no el tzinfo al guardar/leer, a diferencia de PostgreSQL (real)."""
    return [m.astimezone(MADRID) for m in marks]


async def _marks_for(db: AsyncSession, person_key: str, lo: date, hi: date) -> list[datetime]:
    lo_dt, hi_dt = _day_bounds(lo, hi)
    stmt = select(ClockMark.at).where(ClockMark.person_key == person_key, ClockMark.at >= lo_dt, ClockMark.at < hi_dt)
    marks = list((await db.scalars(stmt)).all())
    return _localize_marks(marks)


async def _shifts_for(db: AsyncSession, person_key: str, lo: date, hi: date) -> list[ShiftExpectation]:
    stmt = select(ShiftDay).where(
        ShiftDay.person_key == person_key,
        ShiftDay.day.between(lo, hi),
        ShiftDay.kind == ShiftKind.TRABAJO,
    )
    days = list((await db.scalars(stmt)).all())
    return [ShiftExpectation(d.day, d.start_time, d.end_time) for d in days]


def _comparison_row(
    name: str, department: str | None, results: list[DayComparison], incomplete: list[Any]
) -> list[Any]:
    counts = {"correcto": 0, "desviado": 0, "falta_marcaje": 0, "sin_turno": 0}
    for r in results:
        counts[r.status] += 1
    return [
        name,
        department or "—",
        counts["correcto"],
        counts["desviado"],
        counts["falta_marcaje"],
        counts["sin_turno"],
        len(incomplete),
    ]


def _incomplete_warnings(person_name: str, incomplete: list[datetime]) -> list[dict[str, Any]]:
    return [
        {
            "severity": "data_quality",
            "code": "FICHAJE_INCOMPLETO",
            "message": f"{person_name}: marca sin pareja el {m.strftime('%d/%m/%Y %H:%M')}.",
            "source": "fichajes",
            "context": {"persona": person_name, "fecha": m.isoformat()},
        }
        for m in sorted(incomplete)
    ]


def fichajes_persona(deps: Deps) -> Tool:
    async def handler(p: PersonaPeriodoParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo = p.desde or _week_start(today)
        hi = p.hasta or today
        async with deps.db.session() as db:
            match = await resolve_person(db, PersonaParams(empleado_id=p.empleado_id, nombre=p.nombre), ctx=ctx)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            if not e.person_key:
                return ToolResult(ToolStatus.NOT_FOUND, f"{e.name} no tiene un identificador de fichaje válido.")
            marks = await _marks_for(db, e.person_key, lo, hi)

        sessions, incomplete = pair_marks(marks)
        total_horas = round(sum(s.hours for s in sessions), 2)
        rows = [
            [s.entrada.strftime("%d/%m/%Y"), s.entrada.strftime("%H:%M"), s.salida.strftime("%H:%M"), s.hours]
            for s in sorted(sessions, key=lambda s: s.entrada)
        ]
        return ToolResult(
            ToolStatus.OK,
            {
                "persona": e.name,
                "periodo": f"{fmt_date(lo)} – {fmt_date(hi)}",
                "sesiones_completas": len(sessions),
                "horas_totales": total_horas,
                "marcas_incompletas": len(incomplete),
                "advertencias": _incomplete_warnings(e.name, incomplete),
            },
            table(f"Fichajes · {e.name}", ["Fecha", "Entrada", "Salida", "Horas"], rows),
            focus_person(e),
        )

    return Tool(
        "fichajes_persona",
        "Marcas de fichaje (entrada/salida) reales de una persona en un periodo, ya emparejadas en "
        "sesiones con sus horas. Las marcas sin pareja (p. ej. un olvido de fichar) se listan aparte, "
        "nunca se ocultan ni se adivina su hora de cierre.",
        PersonaPeriodoParams,
        handler,
        permission=Permission.FICHAJES_LEER,
        audit_resource="fichajes",
    )


def comparar_turnos_fichajes(deps: Deps) -> Tool:
    async def handler(p: ComparacionParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo = p.desde or _week_start(today)
        hi = p.hasta or today

        async with deps.db.session() as db:
            if p.empleado_id or (p.nombre or "").strip():
                match = await resolve_person(db, PersonaParams(empleado_id=p.empleado_id, nombre=p.nombre), ctx=ctx)
                if match.employee is None:
                    return person_problem(match, p.nombre)
                employees = [match.employee]
            else:
                stmt = select(Employee).where(Employee.active.is_(True), Employee.person_key.is_not(None))
                if p.departamento:
                    dept = await resolve_department(db, p.departamento)
                    if dept.status is not ToolStatus.OK:
                        return department_problem(dept, p.departamento)
                    stmt = stmt.where(Employee.department_key == dept.key)
                employees = list((await db.scalars(stmt.order_by(Employee.name))).all())

            rows: list[list[Any]] = []
            advertencias: list[dict[str, Any]] = []
            totals = {"correcto": 0, "desviado": 0, "falta_marcaje": 0, "sin_turno": 0}
            incompletas_total = 0
            entrada_devs: list[int] = []
            salida_devs: list[int] = []
            analizados = 0
            for e in employees:
                if not e.person_key:
                    continue
                shifts = await _shifts_for(db, e.person_key, lo, hi)
                marks = await _marks_for(db, e.person_key, lo, hi)
                if not shifts and not marks:
                    continue
                analizados += 1
                results, incomplete = compare_person(shifts, marks, tolerance_minutes=p.tolerancia_minutos)
                rows.append(_comparison_row(e.name, e.department, results, incomplete))
                for r in results:
                    totals[r.status] += 1
                    if r.status == "desviado":
                        entrada_devs.append(r.entrada_desviacion_min or 0)
                        salida_devs.append(r.salida_desviacion_min or 0)
                incompletas_total += len(incomplete)
                advertencias.extend(_incomplete_warnings(e.name, incomplete))

        if analizados == 0:
            return ToolResult(ToolStatus.NOT_FOUND, "No hay turnos ni fichajes en ese periodo para comparar.")

        marcajes_incorrectos = totals["desviado"] + totals["sin_turno"]
        avg_entrada = round(sum(entrada_devs) / len(entrada_devs), 1) if entrada_devs else None
        avg_salida = round(sum(salida_devs) / len(salida_devs), 1) if salida_devs else None
        kpis = [
            {"label": "Personas analizadas", "value": analizados},
            {"label": "Marcajes incorrectos", "value": marcajes_incorrectos},
            {"label": "Desviados de turno", "value": totals["desviado"]},
            {"label": "Sin turno programado", "value": totals["sin_turno"]},
            {"label": "Faltas de marcaje", "value": totals["falta_marcaje"]},
            {"label": "Marcas incompletas", "value": incompletas_total},
        ]

        return ToolResult(
            ToolStatus.OK,
            {
                "periodo": f"{fmt_date(lo)} – {fmt_date(hi)}",
                "personas_analizadas": analizados,
                "marcajes_incorrectos": marcajes_incorrectos,
                "marcajes_desviados": totals["desviado"],
                "marcajes_sin_turno": totals["sin_turno"],
                "faltas_de_marcaje": totals["falta_marcaje"],
                "marcas_incompletas": incompletas_total,
                "desviacion_media_entrada_min": avg_entrada,
                "desviacion_media_salida_min": avg_salida,
                "tolerancia_minutos": p.tolerancia_minutos,
                "advertencias": advertencias,
            },
            {
                "type": "table",
                "title": "Comparación turnos vs. fichajes",
                "kpis": kpis,
                "columns": [
                    "Persona",
                    "Departamento",
                    "Correctos",
                    "Desviados",
                    "Faltas de marcaje",
                    "Sin turno",
                    "Marcas incompletas",
                ],
                "rows": rows,
            },
        )

    return Tool(
        "comparar_turnos_fichajes",
        "Compara, persona a persona, los turnos programados con los fichajes reales (Conectia): "
        "marcajes correctos, desviados del horario programado (más allá de la tolerancia), faltas "
        "de marcaje (turno sin ningún fichaje) y fichajes sin turno programado ese día — cada "
        "categoría por separado, nunca mezcladas. Las marcas de fichaje sin pareja (un fichaje "
        "suelto, sin su entrada o salida correspondiente) se señalan aparte explícitamente, nunca "
        "se ocultan ni se cuentan como falta de marcaje. Sin persona ni departamento, compara toda "
        "la plantilla con turno o fichaje en el periodo.",
        ComparacionParams,
        handler,
        permission=Permission.FICHAJES_LEER,
        audit_resource="fichajes",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(fichajes_persona(deps))
    registry.register(comparar_turnos_fichajes(deps))
