"""Informe premium comparativo turnos↔fichajes: resumen ejecutivo de un departamento en una semana
(u otro periodo) y detalle día a día de cada empleado — horas programadas, nocturnas, trabajadas,
extra (día/noche) y balance en %, siempre sobre datos ya validados por ``comparison.py``/``hours.py``.

Hasta que exista la API real de Conectia, el Excel se importa desde un adjunto subido en la propia
conversación (``adjunto_id``) — nunca un segundo motor de importación: la misma función de
``fichajes.importer`` que ya hace el cruce por nombre."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import ClockMark, Employee, ShiftDay, ShiftTypeCatalog
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import Deps, department_problem, fmt_date, resolve_department
from mia.modules.rrhh.fichajes.comparison import DayComparison, ShiftExpectation, compare_person
from mia.modules.rrhh.fichajes.hours import DayHours, compute_day_hours
from mia.modules.rrhh.fichajes.importer import import_from_attachment
from mia.modules.rrhh.fichajes.shift_match import match_shift_type
from mia.modules.rrhh.fichajes.tools import MADRID, _localize_marks
from mia.reporting.document import Block, Document
from mia.modules.rrhh.informes.persist import persist_document_report

KEYWORDS = (
    "informe de turnos y fichajes", "informe comparativo de turnos", "comparativa de fichajes",
    "informe de presencia", "cuadrante vs fichaje", "balance de horas", "horas extra nocturnas",
    "informe de horas nocturnas", "resumen de fichajes por departamento",
)
"""Ver `empleados.tools.KEYWORDS` para el criterio."""

DEFAULT_TOLERANCE_MIN = 15
class InformeComparativoTurnosFichajesParams(BaseModel):
    departamento: str = Field(description="Departamento a analizar — el informe siempre es por departamento")
    anio_iso: int | None = Field(
        default=None, description="Año ISO de la semana (por defecto, el año en curso); solo se usa junto con semana_iso"
    )
    semana_iso: int | None = Field(
        default=None, ge=1, le=53,
        description="Número de semana ISO (1-53): si se indica, el periodo es esa semana completa (lunes a domingo)",
    )
    desde: date | None = Field(default=None, description="Inicio del periodo, alternativa a semana_iso")
    hasta: date | None = Field(default=None, description="Fin del periodo, alternativa a semana_iso (por defecto, hoy)")
    adjunto_id: str | None = Field(
        default=None,
        description="ID del adjunto Excel de fichajes de Conectia subido en esta conversación; si se indica, se "
        "importa antes de comparar (hasta que exista la conexión real con Conectia)",
    )
    tolerancia_minutos: int = Field(
        default=DEFAULT_TOLERANCE_MIN,
        description="Margen en minutos para considerar un fichaje 'correcto' frente al turno programado",
    )
    formato: Literal["pdf", "xlsx", "pptx", "html", "docx"] = Field(default="pdf", description="Formato del documento")
    titulo: str | None = Field(default=None, description="Título personalizado del informe")


class _PersonHours:
    __slots__ = ("employee", "results", "day_hours", "incomplete", "shift_by_day")

    def __init__(
        self,
        employee: Employee,
        results: list[DayComparison],
        day_hours: list[DayHours],
        incomplete: list[datetime],
        shift_by_day: dict[date, ShiftExpectation],
    ) -> None:
        self.employee = employee
        self.results = results
        self.day_hours = day_hours
        self.incomplete = incomplete
        self.shift_by_day = shift_by_day

    @property
    def totals(self) -> dict[str, float]:
        return {
            "horas_programadas": round(sum(h.horas_programadas for h in self.day_hours), 2),
            "horas_nocturnas_normales": round(sum(h.horas_nocturnas_normales for h in self.day_hours), 2),
            "horas_trabajadas": round(sum(h.horas_trabajadas for h in self.day_hours), 2),
            "horas_extra": round(sum(h.horas_extra for h in self.day_hours), 2),
            "horas_extra_nocturnas": round(sum(h.horas_extra_nocturnas for h in self.day_hours), 2),
            "horas_extra_diurnas": round(sum(h.horas_extra_diurnas for h in self.day_hours), 2),
            "balance": round(sum(h.balance for h in self.day_hours), 2),
        }

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {"correcto": 0, "desviado": 0, "falta_marcaje": 0, "sin_turno": 0}
        for r in self.results:
            counts[r.status] += 1
        return counts


def _week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _resolve_period(
    p: InformeComparativoTurnosFichajesParams, today: date, imported_period: tuple[datetime, datetime] | None
) -> tuple[ToolStatus, date, date]:
    """``semana_iso``/``desde``/``hasta`` explícitos SIEMPRE ganan (el usuario puede querer acotar a
    un subconjunto). Si no se dio ninguno de los dos Y se importó un adjunto, el periodo se deriva de
    las fechas REALES del propio fichero (``imported_period``) — nunca de un número de semana
    adivinado: confirmado contra datos reales (2026-10-21) que la "semana" de Conectia (nombre del
    fichero) y el número ISO de ``ShiftDay.iso_week`` no tienen por qué coincidir (el fichero
    "MARCAJES SEMANA 41 PISOS.xlsx" correspondía en realidad a fechas de la semana ISO 42), así que
    forzar aquí un número de semana sería comparar contra el periodo equivocado. Sin adjunto y sin
    fechas explícitas, se cae a la semana en curso, igual que el resto de herramientas de fichajes."""
    if p.semana_iso:
        year = p.anio_iso or today.isocalendar()[0]
        try:
            lo = date.fromisocalendar(year, p.semana_iso, 1)
        except ValueError:
            return ToolStatus.INVALID_ARGUMENTS, today, today
        return ToolStatus.OK, lo, lo + timedelta(days=6)
    if p.desde or p.hasta:
        return ToolStatus.OK, p.desde or _week_start(today), p.hasta or today
    if imported_period:
        lo_dt, hi_dt = imported_period
        return ToolStatus.OK, lo_dt.date(), hi_dt.date()
    return ToolStatus.OK, _week_start(today), today


def _shift_label(shift: ShiftExpectation | None) -> str:
    """P. ej. "Piscina 10:00-18:00" — el turno concreto que tenía programado ese día, para que el
    detalle diario no se quede solo en el estado (correcto/desviado/…)."""
    if shift is None or not shift.start_time or not shift.end_time:
        return "—"
    area = f"{shift.area} " if shift.area else ""
    return f"{area}{shift.start_time}-{shift.end_time}"


def _import_warnings(report: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for raw_name, count in report.unmatched.items():
        warnings.append({
            "severity": "data_quality", "code": "FICHAJE_SIN_CRUZAR",
            "message": f"«{raw_name}»: {count} fila(s) del Excel sin ninguna persona que coincida.",
            "source": "fichajes_import", "context": {"nombre": raw_name, "filas": count},
        })
    for raw_name, count in report.ambiguous.items():
        warnings.append({
            "severity": "data_quality", "code": "FICHAJE_AMBIGUO",
            "message": f"«{raw_name}»: {count} fila(s) con más de una persona que coincide.",
            "source": "fichajes_import", "context": {"nombre": raw_name, "filas": count},
        })
    return warnings


def _build_document(
    departamento: str,
    lo: date,
    hi: date,
    today: date,
    people: list[_PersonHours],
    warnings: list[dict[str, Any]],
    import_summary: dict[str, Any] | None,
) -> Document:
    periodo_label = f"{fmt_date(lo)} – {fmt_date(hi)}"
    blocks: list[Block] = []

    dept_totals = {
        key: round(sum(p.totals[key] for p in people), 2)
        for key in ("horas_programadas", "horas_nocturnas_normales", "horas_trabajadas",
                    "horas_extra", "horas_extra_nocturnas", "horas_extra_diurnas", "balance")
    }
    dept_counts = {"correcto": 0, "desviado": 0, "falta_marcaje": 0, "sin_turno": 0}
    for p in people:
        for k, v in p.status_counts.items():
            dept_counts[k] += v
    incompletas_total = sum(len(p.incomplete) for p in people)
    balance_pct_turno = (
        round(dept_totals["balance"] / dept_totals["horas_programadas"] * 100, 1)
        if dept_totals["horas_programadas"] else None
    )
    balance_pct_fichaje = (
        round(dept_totals["balance"] / dept_totals["horas_trabajadas"] * 100, 1)
        if dept_totals["horas_trabajadas"] else None
    )

    kpis: dict[str, Any] = {
        "Personas analizadas": len(people),
        "Horas programadas": dept_totals["horas_programadas"],
        "Horas trabajadas": dept_totals["horas_trabajadas"],
        "Balance": f"{dept_totals['balance']:+.2f} h",
        "Balance % s/ turno": f"{balance_pct_turno:+.1f}%" if balance_pct_turno is not None else "—",
        "Balance % s/ fichaje": f"{balance_pct_fichaje:+.1f}%" if balance_pct_fichaje is not None else "—",
        "Horas nocturnas (horario)": dept_totals["horas_nocturnas_normales"],
        "Horas extra": dept_totals["horas_extra"],
        "Horas extra nocturnas": dept_totals["horas_extra_nocturnas"],
        "Horas extra diurnas": dept_totals["horas_extra_diurnas"],
        "Marcajes correctos": dept_counts["correcto"],
        "Marcajes desviados": dept_counts["desviado"],
        "Faltas de marcaje": dept_counts["falta_marcaje"],
        "Fichajes sin turno": dept_counts["sin_turno"],
        "Marcas incompletas": incompletas_total,
    }
    if import_summary:
        kpis["Adjunto importado"] = import_summary["adjunto"]
        kpis["Marcas importadas"] = import_summary["marcas_importadas"]
    blocks.append(Block("kpis", f"Resumen ejecutivo · {departamento}", kpis))

    summary_rows = []
    for p in sorted(people, key=lambda x: x.employee.name or ""):
        t = p.totals
        c = p.status_counts
        pct_turno = (round(t["balance"] / t["horas_programadas"] * 100, 1) if t["horas_programadas"] else None)
        pct_fichaje = (round(t["balance"] / t["horas_trabajadas"] * 100, 1) if t["horas_trabajadas"] else None)
        summary_rows.append([
            p.employee.name, t["horas_programadas"], t["horas_trabajadas"],
            f"{t['balance']:+.2f}",
            f"{pct_turno:+.1f}%" if pct_turno is not None else "—",
            f"{pct_fichaje:+.1f}%" if pct_fichaje is not None else "—",
            t["horas_nocturnas_normales"], t["horas_extra_diurnas"], t["horas_extra_nocturnas"],
            c["correcto"], c["desviado"], c["falta_marcaje"], c["sin_turno"], len(p.incomplete),
        ])
    blocks.append(Block(
        "table",
        f"Resumen por persona · {periodo_label}",
        {
            "columns": [
                "Persona", "Programadas", "Trabajadas", "Balance", "Balance % turno", "Balance % fichaje",
                "Nocturnas (horario)", "Extra diurnas", "Extra nocturnas",
                "Correctos", "Desviados", "Faltas", "Sin turno", "Incompletas",
            ],
            "rows": summary_rows,
        },
    ))

    for p in sorted(people, key=lambda x: x.employee.name or ""):
        blocks.append(Block("section", p.employee.name, {"Departamento": departamento, "Periodo": periodo_label}))
        detail_rows = []
        for r, h in zip(p.results, p.day_hours, strict=True):
            session = r.session
            detail_rows.append([
                fmt_date(r.day), r.status, _shift_label(p.shift_by_day.get(r.day)),
                session.entrada.strftime("%H:%M") if session else "—",
                session.salida.strftime("%H:%M") if session else "—",
                h.horas_programadas, h.horas_trabajadas, f"{h.balance:+.2f}",
                h.horas_nocturnas_normales, h.horas_extra_diurnas, h.horas_extra_nocturnas,
            ])
        blocks.append(Block(
            "table",
            f"Detalle · {p.employee.name}",
            {
                "columns": [
                    "Fecha", "Estado", "Turno", "Entrada real", "Salida real",
                    "Programadas", "Trabajadas", "Balance",
                    "Nocturnas (horario)", "Extra diurnas", "Extra nocturnas",
                ],
                "rows": detail_rows,
            },
        ))

    if warnings:
        blocks.append(Block("warnings", "Avisos de calidad de datos", {"items": warnings}))

    return Document(
        title=f"Informe comparativo turnos · fichajes — {departamento}",
        subtitle=f"Periodo: {periodo_label} · Generado: {fmt_date(today)}",
        badges=[departamento, periodo_label],
        blocks=blocks,
    )


def informe_comparativo_turnos_fichajes(deps: Deps) -> Tool:
    async def handler(p: InformeComparativoTurnosFichajesParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
        if dept.status is not ToolStatus.OK:
            return department_problem(dept, p.departamento)

        today = ctx.now.date()

        warnings: list[dict[str, Any]] = []
        import_summary: dict[str, Any] | None = None
        imported_period: tuple[datetime, datetime] | None = None
        if p.adjunto_id:
            svc = ctx.attachment_service
            if svc is None:
                return ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "La funcionalidad de adjuntos no está activa.")
            record = svc.get_for_user(p.adjunto_id, ctx.user.user_id)
            if record is None:
                return ToolResult(ToolStatus.NOT_FOUND, f"Adjunto {p.adjunto_id} no encontrado o expirado.")
            content = await svc.get_bytes(p.adjunto_id, ctx.user.user_id)
            if not content:
                return ToolResult(ToolStatus.ERROR, "No se pudo leer el contenido del adjunto.")
            try:
                import_report = await import_from_attachment(deps.db, content, record.original_filename, now=ctx.now)
            except ValueError as exc:
                return ToolResult(ToolStatus.INVALID_ARGUMENTS, {"mensaje": str(exc)})
            import_summary = {
                "adjunto": record.original_filename,
                "filas_leidas": import_report.rows_read,
                "marcas_importadas": import_report.imported,
                "sin_cruzar": import_report.unmatched_rows,
                "ambiguas": import_report.ambiguous_rows,
            }
            imported_period = import_report.period
            warnings.extend(_import_warnings(import_report))

        status, lo, hi = _resolve_period(p, today, imported_period)
        if status is not ToolStatus.OK:
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS,
                f"La semana ISO {p.semana_iso} de {p.anio_iso or today.isocalendar()[0]} no existe.",
            )

        async with deps.db.session() as db:
            employees = list((await db.scalars(
                select(Employee)
                .where(Employee.active.is_(True), Employee.person_key.is_not(None), Employee.department_key == dept.key)
                .order_by(Employee.name)
            )).all())
            if not employees:
                return ToolResult(ToolStatus.NOT_FOUND, f"No hay empleados activos en «{dept.name}».")

            catalog = list((await db.scalars(
                select(ShiftTypeCatalog).where(ShiftTypeCatalog.department_key == dept.key)
            )).all())

            people: list[_PersonHours] = []
            for e in employees:
                shift_rows = list((await db.scalars(
                    select(ShiftDay).where(
                        ShiftDay.person_key == e.person_key,
                        ShiftDay.day.between(lo, hi),
                        ShiftDay.kind == ShiftKind.TRABAJO,
                    )
                )).all())
                marks_raw = list((await db.scalars(
                    select(ClockMark.at).where(
                        ClockMark.person_key == e.person_key,
                        ClockMark.at >= datetime.combine(lo, time.min, tzinfo=MADRID),
                        ClockMark.at < datetime.combine(hi + timedelta(days=1), time.min, tzinfo=MADRID),
                    )
                )).all())
                marks = _localize_marks(marks_raw)
                if not shift_rows and not marks:
                    continue

                expectations: list[ShiftExpectation] = []
                for sd in shift_rows:
                    match = match_shift_type(sd, catalog)
                    if match.definition is None and sd.segments:
                        code = "TURNO_NOCTURNIDAD_AMBIGUA" if match.ambiguous else "TURNO_SIN_DEFINICION"
                        detail = (
                            "más de una definición de turno con ese horario en el departamento"
                            if match.ambiguous else
                            "no hay una definición de turno (TipoTurnos) con ese horario exacto"
                        )
                        warnings.append({
                            "severity": "data_quality", "code": code,
                            "message": f"{e.name}, {fmt_date(sd.day)}: {detail} — sus horas nocturnas no se calculan.",
                            "source": "turnos", "context": {"persona": e.name, "fecha": sd.day.isoformat()},
                        })
                    declared_night = match.definition.hours_night if match.definition else None
                    expectations.append(
                        ShiftExpectation(sd.day, sd.start_time, sd.end_time, sd.hours, declared_night, sd.area)
                    )

                results, incomplete = compare_person(expectations, marks, tolerance_minutes=p.tolerancia_minutos)
                by_day = {s.day: s for s in expectations}
                day_hours = [
                    compute_day_hours(by_day.get(r.day) or ShiftExpectation(r.day, None, None, 0.0, None), r.session)
                    for r in results
                ]
                people.append(_PersonHours(e, results, day_hours, incomplete, by_day))
                for m in sorted(incomplete):
                    warnings.append({
                        "severity": "data_quality", "code": "FICHAJE_INCOMPLETO",
                        "message": f"{e.name}: marca sin pareja el {m.strftime('%d/%m/%Y %H:%M')}.",
                        "source": "fichajes", "context": {"persona": e.name, "fecha": m.isoformat()},
                    })

        if not people:
            return ToolResult(ToolStatus.NOT_FOUND, "No hay turnos ni fichajes en ese periodo para comparar.")

        document = _build_document(dept.name or p.departamento, lo, hi, today, people, warnings, import_summary)
        if p.titulo:
            document.title = p.titulo

        return await persist_document_report(
            deps, ctx, document,
            formato=p.formato,
            tool_name="informe_comparativo_turnos_fichajes",
            default_file_stem="informe_turnos_fichajes",
            extra_summary={
                "periodo": f"{fmt_date(lo)} – {fmt_date(hi)}",
                "departamento": dept.name,
                "personas_analizadas": len(people),
                "avisos_calidad_datos": len(warnings),
                "advertencias": warnings,
            },
        )

    return Tool(
        "informe_comparativo_turnos_fichajes",
        "Genera el informe PREMIUM comparativo de turnos vs. fichajes de un departamento en una semana "
        "(u otro periodo): resumen ejecutivo del departamento y detalle día a día de cada empleado — "
        "horas programadas, horas nocturnas del horario, horas trabajadas, horas extra (desglosadas en "
        "diurnas y nocturnas) y balance de horas en %, tanto sobre el turno como sobre el fichaje. "
        "Hasta que exista la conexión con Conectia, indica 'adjunto_id' con el Excel de fichajes que el "
        "usuario haya subido en esta conversación para importarlo antes de comparar. Especifica el "
        "periodo con 'semana_iso' (+ opcionalmente 'anio_iso') o con 'desde'/'hasta'.",
        InformeComparativoTurnosFichajesParams,
        handler,
        permission=Permission.FICHAJES_LEER,
        audit_resource="fichajes",
        timeout_seconds=300,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(informe_comparativo_turnos_fichajes(deps))
