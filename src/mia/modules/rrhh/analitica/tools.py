"""Panel y analítica de RRHH: panel ejecutivo, comparación de departamentos, cobertura semanal,
analítica de vacaciones, altas y calidad de datos."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import (
    Candidate,
    Employee,
    NewHire,
    Payslip,
    ShiftDay,
    TtTimesheet,
    Vacation,
    VacationBalance,
)
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import Deps, confirmed_vacations, department_problem, fmt_date, resolve_department, table
from mia.modules.rrhh.turnos.periods import absence_periods
from mia.modules.rrhh.turnos.tools import franja_of
from mia.text import normalize_key


async def _department_snapshot(db: AsyncSession, day: date, dept_key: str | None) -> dict[str, Any]:
    employees = select(Employee).where(Employee.active.is_(True))
    if dept_key:
        employees = employees.where(Employee.department_key == dept_key)
    staff = list((await db.scalars(employees)).all())
    shifts_q = select(ShiftDay).where(ShiftDay.day == day)
    if dept_key:
        shifts_q = shifts_q.where(ShiftDay.department_key.like(f"%{dept_key}%"))
    shifts = list((await db.scalars(shifts_q)).all())
    working = [s for s in shifts if s.kind == ShiftKind.TRABAJO]
    emails = {e.email for e in staff if e.email}
    balances = (
        (
            await db.execute(
                select(VacationBalance.current_balance).where(
                    VacationBalance.year == day.year, VacationBalance.employee_email.in_(emails)
                )
            )
        )
        .scalars()
        .all()
    )
    pending = await db.scalar(
        select(func.count())
        .select_from(Vacation)
        .where(Vacation.employee_email.in_(emails), func.lower(Vacation.status) == "pendiente")
    )
    return {
        "plantilla_activa": len(staff),
        "trabajando": len(working),
        "trabajando_por_franja": dict(Counter(franja_of(s) or "sin horario" for s in working)),
        "horas_programadas": round(sum(s.hours or 0 for s in working), 1),
        "ausentes_por_tipo": dict(
            Counter(s.kind for s in shifts if s.kind not in {ShiftKind.TRABAJO, ShiftKind.DESCANSO})
        ),
        "descansan": sum(1 for s in shifts if s.kind == ShiftKind.DESCANSO),
        "sin_turno_publicado": max(0, len(staff) - len(shifts)) if dept_key else None,
        "saldo_medio_vacaciones": round(sum(b for b in balances if b is not None) / len(balances), 1)
        if balances
        else None,
        "saldos_negativos": sum(1 for b in balances if b is not None and b < 0),
        "solicitudes_pendientes": int(pending or 0),
    }


# ------------------------------------------------------------------ panel
class PanelParams(BaseModel):
    fecha: date | None = Field(default=None, description="Día del panel (por defecto hoy)")
    departamento: str | None = Field(default=None, description="Para el panel de un departamento (departamento 360)")


def panel(deps: Deps) -> Tool:
    async def handler(p: PanelParams, ctx: ToolContext) -> ToolResult:
        day = p.fecha or ctx.now.date()
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            snapshot = await _department_snapshot(db, day, dept.key)
            absences = await absence_periods(db, lo=day, hi=day, department_like=dept.key)
            coming_back = await absence_periods(db, lo=day, hi=day + timedelta(days=7), department_like=dept.key)
            by_dept = (
                await db.execute(
                    select(Employee.department, func.count())
                    .where(Employee.active.is_(True))
                    .group_by(Employee.department)
                    .order_by(func.count().desc())
                )
            ).all()
            last_month = (day.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            slips = await db.scalar(select(func.count()).select_from(Payslip).where(Payslip.period == last_month))
            tt = (
                await db.execute(
                    select(func.count(), func.sum(TtTimesheet.hours_total), func.sum(TtTimesheet.amount)).where(
                        TtTimesheet.day.between(day.replace(day=1), day)
                    )
                )
            ).one()
            fresh = await deps.freshness(db, "empleados", "turnos", "vacaciones")
        returns = sorted(
            [x for x in coming_back if x.return_shift and day <= x.return_shift.day <= day + timedelta(days=7)],
            key=lambda x: x.return_shift.day if x.return_shift else day,
        )
        longest = max(absences, key=lambda x: (day - x.start).days, default=None)
        kpis = {
            **snapshot,
            "bajas_en_curso": sum(1 for x in absences if x.kind == ShiftKind.BAJA),
            "vacaciones_en_curso": sum(1 for x in absences if x.kind == ShiftKind.VACACIONES),
            "reincorporaciones_7_dias": len(returns),
            f"nominas_de_{last_month}": int(slips or 0),
        }
        if not dept.key:
            kpis["trabajo_temporal_mes"] = {
                "boletines": int(tt[0] or 0),
                "horas": round(tt[1] or 0, 1),
                "importe": round(tt[2] or 0, 2),
            }
        summary: dict[str, Any] = {
            "fecha": day.isoformat(),
            "ambito": dept.name or "toda la plantilla",
            "indicadores": kpis,
            "baja_mas_larga_en_curso": (
                {
                    "persona": longest.name,
                    "desde": longest.start.isoformat(),
                    "dias": (day - longest.start).days + 1,
                }
                if longest and longest.kind == ShiftKind.BAJA
                else None
            ),
            "proximas_reincorporaciones": [
                {
                    "persona": x.name,
                    "departamento": x.department,
                    "motivo": x.kind,
                    "vuelve": x.return_shift.day.isoformat() if x.return_shift else None,
                }
                for x in returns[:10]
            ],
            **fresh,
        }
        if not dept.key:
            summary["plantilla_por_departamento"] = {d or "Sin dato": n for d, n in by_dept}
        presentation = {
            "type": "dashboard",
            "title": f"Panel RRHH · {dept.name or 'Sunset Beach Club'} · {fmt_date(day)}",
            "kpis": kpis,
            "tables": [
                table(
                    "Próximas reincorporaciones",
                    ["Persona", "Departamento", "Motivo", "Vuelve"],
                    [
                        [r["persona"], r["departamento"], r["motivo"], r["vuelve"]]
                        for r in summary["proximas_reincorporaciones"]
                    ],
                ),
                table(
                    "Plantilla por departamento",
                    ["Departamento", "Personas"],
                    [[d, n] for d, n in (summary.get("plantilla_por_departamento") or {}).items()],
                ),
            ],
        }
        return ToolResult(ToolStatus.OK, summary, presentation, {"foco_departamento": dept.name} if dept.name else {})

    return Tool(
        "panel_rrhh",
        "Panel ejecutivo de RRHH (o de un departamento: departamento 360) para un día: plantilla, quién "
        "trabaja por franja, ausencias, bajas, reincorporaciones, saldos, pendientes, nóminas y ETT.",
        PanelParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
    )


# ------------------------------------------------------------------ comparar departamentos
class CompararParams(BaseModel):
    departamentos: list[str] = Field(description="Departamentos a comparar (2 o más)", min_length=2, max_length=8)
    fecha: date | None = Field(default=None, description="Foto de UN día (por defecto hoy)")
    desde: date | None = Field(
        default=None, description="Inicio de un PERIODO: balance de ausencias entre desde y hasta"
    )
    hasta: date | None = Field(default=None, description="Fin del periodo")


SNAPSHOT_LABELS = {
    "plantilla_activa": "Plantilla activa",
    "trabajando": "Trabajando",
    "horas_programadas": "Horas programadas",
    "descansan": "Descansan",
    "sin_turno_publicado": "Sin turno publicado",
    "saldo_medio_vacaciones": "Saldo medio de vacaciones",
    "saldos_negativos": "Saldos negativos",
    "solicitudes_pendientes": "Solicitudes pendientes",
}


def _kind_stats(periods: list[Any], today: date, lo: date, hi: date) -> dict[str, dict[str, float]]:
    """Por tipo de ausencia: periodos, empleados, días acumulados en la ventana, media y el más largo."""
    groups: dict[str, list[Any]] = defaultdict(list)
    for x in periods:
        groups[x.kind].append(x)
    out = {}
    for kind, items in groups.items():
        days = [x.days_within(lo, hi) for x in items]
        out[kind] = {
            "periodos": len(items),
            "empleados": len({x.person_key for x in items}),
            "dias_acumulados": sum(days),
            "duracion_media_dias": round(sum(days) / len(items), 2),
            "periodo_mas_largo_dias": max(days),
        }
    return out


async def _compare_period(deps: Deps, p: CompararParams, lo: date, hi: date, today: date) -> ToolResult:
    """Balance de ausencias por departamento en un periodo (p. ej. bajas de Pisos y Recepción en agosto)."""
    columns_data: dict[str, dict[str, Any]] = {}
    async with deps.db.session() as db:
        for name in p.departamentos:
            dept = await resolve_department(db, name)
            if dept.status is not ToolStatus.OK or not dept.key:
                return department_problem(dept, name)
            headcount = int(
                (
                    await db.execute(
                        select(func.count()).where(Employee.active.is_(True), Employee.department_key == dept.key)
                    )
                ).scalar_one()
            )
            periods = await absence_periods(db, lo=lo, hi=hi, department_like=dept.key, only_active=True)
            columns_data[dept.name or name] = {"plantilla": headcount, "tipos": _kind_stats(periods, today, lo, hi)}
    kinds = sorted({k for d in columns_data.values() for k in d["tipos"]}, key=lambda k: (k != ShiftKind.BAJA, k))
    labels = {
        "periodos": "periodos",
        "empleados": "personas",
        "dias_acumulados": "días acumulados",
        "duracion_media_dias": "duración media (días)",
        "periodo_mas_largo_dias": "periodo más largo (días)",
    }
    rows: list[list[Any]] = [["Plantilla activa", *(d["plantilla"] for d in columns_data.values())]]
    matrix: dict[str, dict[str, Any]] = {name: {"Plantilla activa": d["plantilla"]} for name, d in columns_data.items()}
    for kind in kinds:
        for key, label in labels.items():
            metric = f"{kind} · {label}"
            values = [d["tipos"].get(kind, {}).get(key, 0) for d in columns_data.values()]
            rows.append([metric, *values])
            for name, value in zip(columns_data, values, strict=True):
                matrix[name][metric] = value
    summary = {
        "periodo": f"{lo.isoformat()} a {hi.isoformat()}",
        "nota": "Balance de todo el periodo (no de un día): personas distintas y días acumulados dentro del periodo.",
        "ausencias_en_el_periodo": matrix,
    }
    title = f"Ausencias por departamento · {fmt_date(lo)} – {fmt_date(hi)}"
    return ToolResult(ToolStatus.OK, summary, table(title, ["Indicador", *columns_data], rows))


def comparar(deps: Deps) -> Tool:
    async def handler(p: CompararParams, ctx: ToolContext) -> ToolResult:
        first, last = p.desde or p.hasta, p.hasta or p.desde
        if first and last and first != last:
            return await _compare_period(deps, p, min(first, last), max(first, last), ctx.now.date())
        day = p.fecha or p.desde or p.hasta or ctx.now.date()
        results: dict[str, Any] = {}
        async with deps.db.session() as db:
            for name in p.departamentos:
                dept = await resolve_department(db, name)
                if dept.status is not ToolStatus.OK or not dept.key:
                    return department_problem(dept, name)
                results[dept.name or name] = await _department_snapshot(db, day, dept.key)
        columns = ["Indicador", *results]
        metrics = [
            "plantilla_activa",
            "trabajando",
            "horas_programadas",
            "descansan",
            "sin_turno_publicado",
            "saldo_medio_vacaciones",
            "saldos_negativos",
            "solicitudes_pendientes",
        ]
        rows = [[SNAPSHOT_LABELS.get(m, m), *(results[d].get(m) for d in results)] for m in metrics]
        kinds = sorted({k for r in results.values() for k in r.get("ausentes_por_tipo", {})})
        rows += [
            [f"Ausentes · {k}", *(results[d].get("ausentes_por_tipo", {}).get(k, 0) for d in results)] for k in kinds
        ]
        return ToolResult(
            ToolStatus.OK,
            {"fecha": day.isoformat(), "comparativa": results},
            table(f"Comparativa de departamentos · {fmt_date(day)}", columns, rows),
        )

    return Tool(
        "comparar_departamentos",
        "Compara departamentos. Sin periodo: FOTO de un día (plantilla, trabajando, horas, ausencias, saldos y "
        "pendientes). Con desde y hasta: BALANCE del periodo de ausencias por departamento (periodos, personas, días "
        "acumulados, duración media y periodo más largo de bajas, vacaciones…). Para «compara las bajas de Pisos y "
        "Recepción en agosto» usa desde=1 y hasta=31 de agosto, NO una fecha suelta.",
        CompararParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
    )


# ------------------------------------------------------------------ cobertura semanal
class CoberturaParams(BaseModel):
    departamento: str | None = None
    semana_de: date | None = Field(default=None, description="Cualquier día de la semana (por defecto, esta)")


def cobertura(deps: Deps) -> Tool:
    async def handler(p: CoberturaParams, ctx: ToolContext) -> ToolResult:
        ref = p.semana_de or ctx.now.date()
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
        async with deps.db.session() as db:
            stmt = select(ShiftDay).where(ShiftDay.day.between(start, end))
            if p.departamento:
                stmt = stmt.where(ShiftDay.department_key.like(f"%{normalize_key(p.departamento)}%"))
            shifts = list((await db.scalars(stmt)).all())
            staff = list((await db.scalars(select(Employee).where(Employee.active.is_(True)))).all())
            fresh = await deps.freshness(db, "turnos")
        published = {s.person_key for s in shifts}
        unpublished = Counter(
            e.department or "Sin dato"
            for e in staff
            if e.person_key
            and e.person_key not in published
            and (not p.departamento or normalize_key(p.departamento) in (e.department_key or ""))
        )
        days: dict[date, Counter[str]] = defaultdict(Counter)
        for s in shifts:
            days[s.day][s.kind] += 1
            if s.kind == ShiftKind.TRABAJO:
                days[s.day][f"franja {franja_of(s) or 'sin horario'}"] += 1
        view = [{"fecha": d.isoformat(), **dict(days[d])} for d in (start + timedelta(days=i) for i in range(7))]
        working: list[int] = [int(days[date.fromisoformat(str(v["fecha"]))][ShiftKind.TRABAJO]) for v in view]
        summary = {
            "semana": f"{start.isoformat()} a {end.isoformat()}",
            "departamento": p.departamento or "toda la plantilla",
            "dias": view,
            "dia_con_menos_personal": view[working.index(min(working))]["fecha"] if shifts else None,
            "personas_activas_sin_turnos_publicados": dict(unpublished.most_common()),
            **fresh,
        }
        cols = ["Fecha", "Trabajo", "Mañana", "Tarde", "Noche", "Descanso", "Vacaciones", "Baja/IT"]
        rows = [
            [
                v["fecha"],
                v.get("Trabajo", 0),
                v.get("franja mañana", 0),
                v.get("franja tarde", 0),
                v.get("franja noche", 0),
                v.get("Descanso", 0),
                v.get("Vacaciones", 0),
                v.get("Baja/IT", 0),
            ]
            for v in view
        ]
        return ToolResult(ToolStatus.OK, summary, table("Cobertura semanal", cols, rows))

    return Tool(
        "cobertura_semanal",
        "Cobertura de una semana día a día (trabajando por franja, descansos y ausencias), por departamento.",
        CoberturaParams,
        handler,
        permission=Permission.TURNOS_LEER,
    )


# ------------------------------------------------------------------ analítica de vacaciones
class AnaliticaVacacionesParams(BaseModel):
    anio: int | None = None
    departamento: str | None = None


def analitica_vacaciones(deps: Deps) -> Tool:
    async def handler(p: AnaliticaVacacionesParams, ctx: ToolContext) -> ToolResult:
        year = p.anio or ctx.now.year
        async with deps.db.session() as db:
            stmt = select(Vacation).where(
                Vacation.start_date <= date(year, 12, 31), Vacation.end_date >= date(year, 1, 1)
            )
            if p.departamento:
                stmt = stmt.where(Vacation.department_key.like(f"%{normalize_key(p.departamento)}%"))
            rows = list((await db.scalars(stmt)).all())
            accepted = await confirmed_vacations(db, rows)
        per_month: Counter[int] = Counter()
        for v in accepted:
            if v.start_date and v.end_date:
                d = max(v.start_date, date(year, 1, 1))
                while d <= min(v.end_date, date(year, 12, 31)):
                    per_month[d.month] += 1
                    d += timedelta(days=1)
        months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        by_month = {months[m - 1]: per_month.get(m, 0) for m in range(1, 13)}
        summary: dict[str, Any] = {
            "anio": year,
            "solicitudes_por_estado": dict(Counter(v.status or "Sin estado" for v in rows)),
            "por_tipo": dict(Counter(v.request_type or "Sin tipo" for v in accepted)),
            "dias_persona_por_mes": by_month,
            "mes_de_mas_demanda": months[per_month.most_common(1)[0][0] - 1] if per_month else None,
            "por_departamento": dict(Counter(v.department or "Sin dato" for v in accepted).most_common(10)),
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Vacaciones {year}: días-persona por mes",
                ["Mes", "Días-persona"],
                [[k, v] for k, v in by_month.items()],
            ),
        )

    return Tool(
        "analitica_vacaciones",
        "Analítica de vacaciones de un año: estados, tipos, días-persona por mes, meses de más demanda y "
        "reparto por departamento.",
        AnaliticaVacacionesParams,
        handler,
        permission=Permission.VACACIONES_LEER,
    )


# ------------------------------------------------------------------ altas
class AltasParams(BaseModel):
    desde: date | None = None
    hasta: date | None = None
    departamento: str | None = None


def altas(deps: Deps) -> Tool:
    async def handler(p: AltasParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(NewHire).order_by(NewHire.created_at.desc())
            rows = list((await db.scalars(stmt)).all())
        if p.departamento:
            rows = [r for r in rows if normalize_key(p.departamento) in normalize_key(r.department)]
        if p.desde:
            rows = [r for r in rows if r.created_at and r.created_at.date() >= p.desde]
        if p.hasta:
            rows = [r for r in rows if r.created_at and r.created_at.date() <= p.hasta]
        items = [
            {
                "nombre": r.name,
                "departamento": r.department,
                "puesto": r.position,
                "registrada": fmt_date(r.created_at.date()) if r.created_at else None,
            }
            for r in rows
        ]
        return ToolResult(
            ToolStatus.OK,
            {
                "total": len(items),
                "altas": items[:40],
                "regla": "Aprovisionamiento: no indica si la persona está activa; la fecha de registro "
                "no es la de incorporación.",
            },
            table(
                "Altas de empleados",
                ["Nombre", "Departamento", "Puesto", "Registrada"],
                [list(i.values()) for i in items],
            ),
        )

    return Tool(
        "altas_empleados",
        "Solicitudes de alta de empleados (aprovisionamiento de cuentas).",
        AltasParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
    )


# ------------------------------------------------------------------ calidad de datos
class SinParametros(BaseModel):
    pass


def calidad(deps: Deps) -> Tool:
    async def handler(_: SinParametros, ctx: ToolContext) -> ToolResult:
        year = ctx.now.year
        async with deps.db.session() as db:
            staff = list((await db.scalars(select(Employee).where(Employee.active.is_(True)))).all())
            balances = set(
                (await db.scalars(select(VacationBalance.employee_email).where(VacationBalance.year == year))).all()
            )
            shift_keys = set((await db.scalars(select(ShiftDay.person_key).distinct())).all())
            candidates = list((await db.scalars(select(Candidate.email))).all())
        checks = {
            "sin_email": [e.name for e in staff if not e.email],
            "sin_documento_identidad": [e.name for e in staff if not e.person_key],
            "sin_departamento": [e.name for e in staff if not e.department],
            "sin_puesto": [e.name for e in staff if not e.position],
            "sin_fecha_nacimiento": [e.name for e in staff if not e.birth_date],
            f"sin_saldo_{year}": [e.name for e in staff if e.email and e.email not in balances],
            "sin_ningun_turno": [e.name for e in staff if e.person_key and e.person_key not in shift_keys],
        }
        duplicated = sum(n - 1 for n in Counter(c for c in candidates if c).values() if n > 1)
        summary = {
            "plantilla_activa": len(staff),
            **{k: len(v) for k, v in checks.items()},
            "candidaturas_con_email_repetido": duplicated,
            "detalle": {k: v[:15] for k, v in checks.items() if v},
            "nota": "Las repeticiones de candidaturas se señalan, no se fusionan.",
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Calidad de datos", ["Comprobación", "Personas"], [[k, len(v)] for k, v in checks.items()]),
        )

    return Tool(
        "calidad_datos",
        "Detecta problemas de calidad de datos en el sistema: empleados activos sin email, sin DNI, "
        "sin departamento, sin puesto, sin fecha de nacimiento, sin saldo de vacaciones o sin ningún "
        "turno publicado; y candidaturas con email repetido. Úsalo ante «¿hay algún problema de calidad "
        "de datos?» o «¿qué datos incompletos hay en el sistema?».",
        SinParametros,
        handler,
        permission=Permission.ADMINISTRAR,
    )


# ------------------------------------------------------------------ tendencia de ausencias
class TendenciaAusenciasParams(BaseModel):
    anio: int | None = Field(default=None, description="Año del análisis (por defecto el actual)")
    departamento: str | None = Field(default=None, description="Filtrar por departamento")
    tipo: str | None = Field(
        default=None,
        description="Tipo concreto: 'Baja/IT', 'Vacaciones', 'Permiso', 'Asuntos propios'. Sin valor: todos.",
    )


def tendencia_ausencias(deps: Deps) -> Tool:
    async def handler(p: TendenciaAusenciasParams, ctx: ToolContext) -> ToolResult:
        year = p.anio or ctx.now.year
        lo, hi = date(year, 1, 1), date(year, 12, 31)
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(ShiftDay).where(
                ShiftDay.day.between(lo, hi),
                ShiftDay.kind.notin_([ShiftKind.TRABAJO, ShiftKind.DESCANSO]),
            )
            if dept.key:
                stmt = stmt.where(ShiftDay.department_key.like(f"%{dept.key}%"))
            if p.tipo:
                stmt = stmt.where(ShiftDay.kind == p.tipo)
            days_data = list((await db.scalars(stmt)).all())

        months_es = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        by_month_kind: dict[int, Counter[str]] = defaultdict(Counter)
        by_month_people: dict[int, set[str]] = defaultdict(set)
        for d in days_data:
            by_month_kind[d.day.month][d.kind] += 1
            if d.person_key:
                by_month_people[d.day.month].add(d.person_key)

        kinds = sorted({d.kind for d in days_data}, key=lambda k: (k != ShiftKind.BAJA, k))
        monthly = [
            {
                "mes": months_es[m - 1],
                "total_dias": sum(by_month_kind[m].values()),
                "personas": len(by_month_people[m]),
                **{k: by_month_kind[m].get(k, 0) for k in kinds},
            }
            for m in range(1, 13)
        ]
        total_days = sum(r["total_dias"] for r in monthly)
        peak = max(monthly, key=lambda r: r["total_dias"], default=None)
        summary = {
            "anio": year,
            "ambito": dept.name or "toda la plantilla",
            "tipo_filtrado": p.tipo or "todos",
            "total_dias_ausencia": total_days,
            "mes_de_mayor_absentismo": peak["mes"] if peak and peak["total_dias"] > 0 else None,
            "por_mes": monthly,
        }
        cols = ["Mes", "Total días", "Personas"] + list(kinds)
        rows = [[r["mes"], r["total_dias"], r["personas"]] + [r.get(k, 0) for k in kinds] for r in monthly]
        return ToolResult(ToolStatus.OK, summary, table(f"Tendencia de ausencias {year}", cols, rows))

    return Tool(
        "tendencia_ausencias",
        "Tendencia mensual de ausencias en un año (por defecto el actual): días totales y desglose por tipo "
        "(bajas, vacaciones, permisos, asuntos propios) mes a mes, con el número de personas afectadas. "
        "Útil para identificar picos de absentismo y patrones estacionales.",
        TendenciaAusenciasParams,
        handler,
        permission=Permission.TURNOS_LEER,
    )


# ------------------------------------------------------------------ ranking de absentismo individual
class RankingAbsentismoParams(BaseModel):
    anio: int | None = Field(default=None, description="Año (por defecto el actual)")
    departamento: str | None = Field(default=None, description="Limitar a un departamento")
    tipo: str | None = Field(
        default=None,
        description="Tipo de ausencia: 'Baja/IT', 'Vacaciones', 'Permiso', 'Asuntos propios'. Sin valor: todos.",
    )
    limite: int = Field(default=20, ge=1, le=100, description="Máximo de personas en el ranking (por defecto 20)")


def ranking_absentismo(deps: Deps) -> Tool:
    async def handler(p: RankingAbsentismoParams, ctx: ToolContext) -> ToolResult:
        year = p.anio or ctx.now.year
        lo, hi = date(year, 1, 1), date(year, 12, 31)
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(ShiftDay).where(
                ShiftDay.day.between(lo, hi),
                ShiftDay.kind.notin_([ShiftKind.TRABAJO, ShiftKind.DESCANSO]),
            )
            if dept.key:
                stmt = stmt.where(ShiftDay.department_key.like(f"%{dept.key}%"))
            if p.tipo:
                stmt = stmt.where(ShiftDay.kind == p.tipo)
            days_data = list((await db.scalars(stmt)).all())

        by_person: dict[str, dict[str, Any]] = defaultdict(lambda: {"nombre": None, "departamento": None, "dias": 0, "periodos": set(), "tipos": Counter()})
        for d in days_data:
            key = d.person_key or d.employee_name or "desconocido"
            rec = by_person[key]
            rec["nombre"] = rec["nombre"] or d.employee_name
            rec["departamento"] = rec["departamento"] or d.department
            rec["dias"] += 1
            rec["tipos"][d.kind] += 1

        ranking = sorted(by_person.values(), key=lambda r: r["dias"], reverse=True)[: p.limite]
        rows = [
            [
                r["nombre"] or "—",
                r["departamento"] or "—",
                r["dias"],
                ", ".join(f"{k}:{v}" for k, v in r["tipos"].most_common()),
            ]
            for r in ranking
        ]
        return ToolResult(
            ToolStatus.OK,
            {
                "anio": year,
                "tipo_filtrado": p.tipo or "todos",
                "ambito": dept.name or "toda la plantilla",
                "total_personas_con_ausencia": len(by_person),
                "ranking": [{"nombre": r["nombre"], "departamento": r["departamento"], "dias_ausencia": r["dias"]} for r in ranking],
            },
            table(
                f"Ranking absentismo {year}",
                ["Persona", "Departamento", "Días de ausencia", "Desglose por tipo"],
                rows,
            ),
        )

    return Tool(
        "ranking_absentismo",
        "Ranking de las personas con más días de ausencia en un año: bajas, vacaciones, permisos y "
        "asuntos propios ordenados de mayor a menor. Útil para identificar patrones individuales de "
        "absentismo. Filtrable por departamento y tipo de ausencia.",
        RankingAbsentismoParams,
        handler,
        permission=Permission.TURNOS_LEER,
    )


# ------------------------------------------------------------------ próximos a jubilación
_EDAD_JUBILACION = 67
"""Edad legal de jubilación ordinaria en España (2027+)."""


class JubilacionParams(BaseModel):
    horizonte_anios: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Años de antelación a la jubilación para considerar «próximo» (por defecto 5)",
    )
    departamento: str | None = Field(default=None, description="Filtrar por departamento")


def proximos_jubilacion(deps: Deps) -> Tool:
    async def handler(p: JubilacionParams, ctx: ToolContext) -> ToolResult:
        from mia.modules.rrhh.empleados.tools import age  # noqa: PLC0415

        today = ctx.now.date()
        threshold = _EDAD_JUBILACION - p.horizonte_anios  # edad mínima para aparecer en la lista
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(Employee).where(Employee.active.is_(True), Employee.birth_date.is_not(None))
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
            staff = list((await db.scalars(stmt)).all())

        proximos = []
        for e in staff:
            current_age = age(e.birth_date, today)
            if current_age is None or current_age < threshold:
                continue
            anos_para_jubilacion = max(0, _EDAD_JUBILACION - current_age)
            proximos.append(
                {
                    "nombre": e.name,
                    "departamento": e.department,
                    "puesto": e.position,
                    "edad_actual": current_age,
                    "anos_para_jubilacion": anos_para_jubilacion,
                    "anio_jubilacion_aproximado": today.year + anos_para_jubilacion,
                }
            )
        proximos.sort(key=lambda x: x["anos_para_jubilacion"])
        return ToolResult(
            ToolStatus.OK,
            {
                "ambito": p.departamento or "toda la empresa",
                "horizonte_anios": p.horizonte_anios,
                "edad_jubilacion_referencia": _EDAD_JUBILACION,
                "total": len(proximos),
                "personas": proximos,
                "nota": (
                    "Edad de jubilación ordinaria de referencia: 67 años (España). "
                    "Puede variar según años cotizados; consulta RRHH para casos individuales."
                ),
            },
            table(
                f"Próximos a jubilación (horizonte {p.horizonte_anios} años)",
                ["Nombre", "Departamento", "Puesto", "Edad actual", "Años para jubilación", "Año aprox."],
                [
                    [p["nombre"], p["departamento"], p["puesto"], p["edad_actual"],
                     p["anos_para_jubilacion"], p["anio_jubilacion_aproximado"]]
                    for p in proximos
                ],
            ),
        )

    return Tool(
        "proximos_jubilacion",
        "Lista de empleados activos próximos a la jubilación ordinaria (referencia: 67 años en España). "
        "Por defecto muestra quienes se jubilarán en los próximos 5 años, ordenados de más a menos urgente. "
        "Úsalo para «¿qué empleados están próximos a jubilarse?» o «¿quién se jubila antes de 2030?».",
        JubilacionParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    from mia.modules.rrhh.analitica.consultas import consulta_cruzada  # noqa: PLC0415
    from mia.modules.rrhh.analitica.cruces import datos_de_personas  # noqa: PLC0415
    from mia.modules.rrhh.analitica.departamento import ficha_departamento  # noqa: PLC0415
    from mia.modules.rrhh.analitica.universal import register as _reg_universal  # noqa: PLC0415

    registry.register(datos_de_personas(deps))
    registry.register(consulta_cruzada(deps))
    registry.register(ficha_departamento(deps))
    for factory in (panel, comparar, cobertura, analitica_vacaciones, tendencia_ausencias, ranking_absentismo, altas, calidad, proximos_jubilacion):
        registry.register(factory(deps))
    _reg_universal(registry, deps)
