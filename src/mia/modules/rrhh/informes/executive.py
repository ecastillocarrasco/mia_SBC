"""Constructor del informe ejecutivo de RRHH.

Reúne datos de múltiples dominios en un único Document corporativo sin
depender del resultado previo de sesión. Pensado para dirección.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.analytics.insights import InsightEngine
from mia.analytics.stats import TimePoint
from mia.data import Employee, Payslip, ShiftDay, TtTimesheet, Vacation, VacationBalance
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import Deps, fmt_date
from mia.modules.rrhh.turnos.periods import absence_periods
from mia.reporting.document import Block, Document

_insight_engine = InsightEngine()


async def build_executive_report(
    deps: Deps,
    lo: date,
    hi: date,
    today: date,
    dept_key: str | None,
    dept_name: str | None,
) -> Document:
    """Construye el Document completo del informe ejecutivo de RRHH."""
    ambito = dept_name or "Sunset Beach Club"
    periodo_label = f"{fmt_date(lo)} – {fmt_date(hi)}"

    async with deps.db.session() as db:
        blocks = await _collect_blocks(db, lo, hi, today, dept_key, ambito, periodo_label)

    return Document(
        title=f"Informe Ejecutivo RRHH · {ambito}",
        subtitle=f"Periodo analizado: {periodo_label} · Generado: {fmt_date(today)}",
        badges=[ambito, str(today.year)],
        blocks=blocks,
    )


async def _collect_blocks(
    db: AsyncSession,
    lo: date,
    hi: date,
    today: date,
    dept_key: str | None,
    ambito: str,
    periodo_label: str,
) -> list[Block]:
    # ── Plantilla ────────────────────────────────────────────────────────────
    staff_q = select(Employee).where(Employee.active.is_(True))
    if dept_key:
        staff_q = staff_q.where(Employee.department_key == dept_key)
    staff = list((await db.scalars(staff_q)).all())
    emails = {e.email for e in staff if e.email}

    by_dept = list(
        (
            await db.execute(
                _maybe_filter(
                    select(Employee.department, func.count())
                    .where(Employee.active.is_(True))
                    .group_by(Employee.department)
                    .order_by(func.count().desc()),
                    dept_key,
                )
            )
        ).all()
    )

    by_position = list(
        (
            await db.execute(
                _maybe_filter(
                    select(Employee.position, func.count())
                    .where(Employee.active.is_(True), Employee.position.is_not(None))
                    .group_by(Employee.position)
                    .order_by(func.count().desc())
                    .limit(15),
                    dept_key,
                )
            )
        ).all()
    )

    # ── Turnos hoy ───────────────────────────────────────────────────────────
    shifts_q = select(ShiftDay).where(ShiftDay.day == today)
    if dept_key:
        shifts_q = shifts_q.where(ShiftDay.department_key.like(f"%{dept_key}%"))
    shifts_today = list((await db.scalars(shifts_q)).all())

    # ── Ausencias en el periodo ───────────────────────────────────────────────
    absence_data = await absence_periods(
        db,
        lo=lo,
        hi=hi,
        department_like=dept_key,
        only_active=True,
    )

    # ── Vacaciones ───────────────────────────────────────────────────────────
    balances = list(
        (
            await db.scalars(
                select(VacationBalance).where(
                    VacationBalance.year == today.year,
                    VacationBalance.employee_email.in_(emails),
                )
            )
        ).all()
    )
    pending_vac = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(Vacation)
                .where(Vacation.employee_email.in_(emails), func.lower(Vacation.status) == "pendiente")
            )
        )
        or 0
    )

    # ── Nóminas ──────────────────────────────────────────────────────────────
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    payslips_last = int(
        (await db.scalar(select(func.count()).select_from(Payslip).where(Payslip.period == last_month))) or 0
    )

    # ── ETT (sólo global, no filtrada por departamento) ───────────────────────
    tt_summary: dict[str, Any] | None = None
    tt_by_company: list[Any] = []
    if not dept_key:
        tt_row = (
            await db.execute(
                select(
                    func.count(),
                    func.sum(TtTimesheet.hours_total),
                    func.sum(TtTimesheet.amount),
                ).where(TtTimesheet.day.between(lo, hi))
            )
        ).one()
        tt_summary = {
            "boletines": int(tt_row[0] or 0),
            "horas_totales": round(float(tt_row[1] or 0), 1),
            "importe_total": round(float(tt_row[2] or 0), 2),
        }
        if tt_summary["boletines"] > 0:
            tt_by_company = list(
                (
                    await db.execute(
                        select(
                            TtTimesheet.company,
                            func.count(),
                            func.sum(TtTimesheet.hours_total),
                            func.sum(TtTimesheet.amount),
                        )
                        .where(TtTimesheet.day.between(lo, hi))
                        .group_by(TtTimesheet.company)
                        .order_by(func.sum(TtTimesheet.hours_total).desc())
                    )
                ).all()
            )

    # ── Cálculos ─────────────────────────────────────────────────────────────
    total_staff = len(staff)
    working_today = sum(1 for s in shifts_today if s.kind == ShiftKind.TRABAJO)
    absents_today = sum(1 for s in shifts_today if s.kind not in {ShiftKind.TRABAJO, ShiftKind.DESCANSO})
    resting_today = sum(1 for s in shifts_today if s.kind == ShiftKind.DESCANSO)
    without_shift_today = max(0, total_staff - len(shifts_today))

    abs_by_kind: Counter[str] = Counter(x.kind for x in absence_data)
    total_absence_days = sum(x.days_within(lo, hi) for x in absence_data)
    people_absent = len({x.person_key for x in absence_data})
    avg_absence_duration = round(total_absence_days / len(absence_data), 1) if absence_data else 0

    valid_balances = [b.current_balance for b in balances if b.current_balance is not None]
    avg_balance = round(sum(valid_balances) / len(valid_balances), 1) if valid_balances else None
    negative_balances = sum(1 for b in valid_balances if b < 0)

    # ── Blocks ───────────────────────────────────────────────────────────────
    blocks: list[Block] = []

    # 1 · KPIs de dirección
    kpis: dict[str, Any] = {
        "Plantilla activa": total_staff,
        "Trabajando hoy": working_today,
        "Ausentes hoy": absents_today,
        "Descansando hoy": resting_today,
        "Sin turno hoy": without_shift_today,
        "Bajas IT en periodo": abs_by_kind.get(ShiftKind.BAJA, 0),
        "Personas con ausencia": people_absent,
        "Días de absentismo": total_absence_days,
        "Duración media ausencia": f"{avg_absence_duration} días",
        "Saldo medio vacaciones": f"{avg_balance} días" if avg_balance is not None else "—",
        "Saldos negativos": negative_balances,
        "Sol. vacaciones pendientes": pending_vac,
        f"Nóminas {last_month}": payslips_last,
    }
    if tt_summary:
        kpis["ETT horas en periodo"] = tt_summary["horas_totales"]
        kpis["ETT importe en periodo"] = f"{tt_summary['importe_total']:,.2f} €"
    blocks.append(Block("kpis", "Resumen ejecutivo", kpis))

    # 2 · Plantilla por departamento (chartable: 2 columnas → auto-gráfica)
    if by_dept:
        blocks.append(
            Block(
                "table",
                "Plantilla por departamento",
                {
                    "columns": ["Departamento", "Personas"],
                    "rows": [[dept or "Sin dato", cnt] for dept, cnt in by_dept],
                },
            )
        )

    # 3 · Distribución por puesto (top-15)
    if by_position:
        blocks.append(
            Block(
                "table",
                "Distribución por puesto",
                {
                    "columns": ["Puesto", "Personas"],
                    "rows": [[pos or "Sin dato", cnt] for pos, cnt in by_position],
                },
            )
        )

    # 4 · Absentismo detallado por tipo
    if absence_data:
        by_kind_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"periodos": 0, "personas": set(), "dias": []})
        for x in absence_data:
            k = x.kind
            by_kind_stats[k]["periodos"] += 1
            by_kind_stats[k]["personas"].add(x.person_key)
            by_kind_stats[k]["dias"].append(x.days_within(lo, hi))

        abs_rows = []
        for kind in sorted(by_kind_stats, key=lambda k: (k != ShiftKind.BAJA, k)):
            s = by_kind_stats[kind]
            dias = s["dias"]
            abs_rows.append(
                [
                    kind,
                    s["periodos"],
                    len(s["personas"]),
                    sum(dias),
                    round(sum(dias) / len(dias), 1) if dias else 0,
                    max(dias) if dias else 0,
                ]
            )
        blocks.append(
            Block(
                "table",
                f"Absentismo · {periodo_label}",
                {
                    "columns": [
                        "Tipo",
                        "Periodos",
                        "Personas",
                        "Días acumulados",
                        "Duración media",
                        "Período más largo",
                    ],
                    "rows": abs_rows,
                },
            )
        )

        # Tendencia mensual — agregado total por mes (chartable)
        by_month: Counter[str] = Counter()
        cursor = lo.replace(day=1)
        while cursor <= hi:
            if cursor.month == 12:
                next_month = cursor.replace(year=cursor.year + 1, month=1)
            else:
                next_month = cursor.replace(month=cursor.month + 1)
            month_end = min(hi, next_month - timedelta(days=1))
            month_start = max(lo, cursor)
            # Misma lógica de solapamiento de absence_periods.days_within,
            # pero acotada a cada mes natural; la suma debe coincidir con el periodo.
            days = sum(x.days_within(month_start, month_end) for x in absence_data)
            if days:
                by_month[cursor.strftime("%Y-%m")] = days
            cursor = next_month
        trend_rows = [[mes, days] for mes, days in sorted(by_month.items())]
        if trend_rows:
            blocks.append(
                Block(
                    "table",
                    "Tendencia mensual de absentismo",
                    {"columns": ["Mes", "Días de ausencia"], "rows": trend_rows},
                )
            )
            # Hallazgos deterministas sobre esa misma serie (sección 16: "cada afirmación cuantitativa
            # debe estar respaldada por fuente/métrica/periodo/valor") — el LLM podrá redactarlos en
            # fases futuras, pero el VALOR sale siempre de aquí, nunca inventado. Con un solo mes de
            # datos no hay tendencia que detectar (from_time_series exige ≥2 puntos): no se añade un
            # bloque vacío ni uno con una afirmación sin base.
            trend_points = [TimePoint(label=mes, value=float(dias)) for mes, dias in trend_rows]
            findings = _insight_engine.from_time_series(trend_points, label="el absentismo", unit="días")
            if findings:
                blocks.append(
                    Block(
                        "section",
                        "Hallazgos · Absentismo",
                        {f"Hallazgo {i}": f.text for i, f in enumerate(findings, start=1)},
                    )
                )

    # 5 · Saldos de vacaciones — distribución por rangos (chartable)
    if valid_balances:
        ranges_ordered = ["Más de 20 días", "10 a 20 días", "0 a 9 días", "Saldo negativo"]
        ranges: Counter[str] = Counter()
        for b in valid_balances:
            if b < 0:
                ranges["Saldo negativo"] += 1
            elif b < 10:
                ranges["0 a 9 días"] += 1
            elif b < 20:
                ranges["10 a 20 días"] += 1
            else:
                ranges["Más de 20 días"] += 1
        without = total_staff - len(valid_balances)
        balance_rows = [[rng, ranges[rng]] for rng in ranges_ordered if ranges[rng] > 0]
        if without > 0:
            balance_rows.append(["Sin saldo registrado", without])
        blocks.append(
            Block(
                "table",
                f"Distribución de saldos de vacaciones · {today.year}",
                {"columns": ["Rango", "Personas"], "rows": balance_rows},
            )
        )

    # 6 · ETT por empresa (chartable)
    if tt_by_company:
        blocks.append(
            Block(
                "table",
                f"Trabajo temporal · {periodo_label}",
                {
                    "columns": ["Empresa", "Boletines", "Horas", "Importe (€)"],
                    "rows": [
                        [company, int(cnt), round(float(hours or 0), 1), round(float(amount or 0), 2)]
                        for company, cnt, hours, amount in tt_by_company
                    ],
                },
            )
        )

    return blocks


def _maybe_filter(stmt: Any, dept_key: str | None) -> Any:
    if dept_key:
        return stmt.where(Employee.department_key == dept_key)
    return stmt
