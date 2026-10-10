"""Capacidades analíticas universales — FASE C.

Nuevas tools que permiten análisis abiertos y composición dinámica:

  analizar_departamento    — «¿Qué está pasando con Cocina?» → análisis completo
  tendencia_metrica        — serie temporal de cualquier métrica de ausencias/plantilla
  comparar_universal       — comparación multi-grupo, multi-métrica, con insights
  analisis_temporal        — comparación YoY / MoM / periodo a periodo
  distribucion_plantilla   — distribución de la plantilla por cualquier dimensión

Estas tools NO duplican la lógica de las especializadas (panel_rrhh, comparar_departamentos,
tendencia_ausencias…); las AMPLÍAN para responder consultas que antes requerían múltiples
herramientas o no tenían herramienta específica.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mia.analytics.insights import Insight, InsightEngine
from mia.analytics.stats import TimePoint, time_series_stats
from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, ShiftDay, TtTimesheet, VacationBalance
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.analitica.tools import _department_snapshot
from mia.modules.rrhh.common import (
    Deps,
    department_problem,
    resolve_department,
    table,
)
from mia.modules.rrhh.turnos.periods import absence_periods
from mia.query.period import PeriodEngine

_period_engine = PeriodEngine()
_insight_engine = InsightEngine()

ABSENT_KINDS = (ShiftKind.BAJA, ShiftKind.VACACIONES, ShiftKind.PERMISO, ShiftKind.ASUNTOS_PROPIOS)


# ─────────────────────────────────────────────────────────────────────────────
# analizar_departamento
# ─────────────────────────────────────────────────────────────────────────────
class AnalizarParams(BaseModel):
    departamento: str = Field(description="Nombre del departamento a analizar")
    desde: date | None = Field(
        default=None,
        description="Inicio del periodo de análisis de ausencias (por defecto: hace 6 meses)",
    )
    hasta: date | None = Field(
        default=None,
        description="Fin del periodo (por defecto: hoy)",
    )
    incluir_vacaciones: bool = Field(default=True, description="Incluir análisis de vacaciones")
    incluir_ett: bool = Field(default=False, description="Incluir uso de ETT")
    profundidad: Literal["resumen", "completo"] = Field(
        default="completo",
        description="'resumen' devuelve solo KPIs; 'completo' añade tendencias e insights",
    )


def analizar_departamento(deps: Deps) -> Tool:
    """Análisis integral de un departamento: plantilla, ausencias, tendencias, insights."""

    async def handler(p: AnalizarParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        hi = p.hasta or today
        lo = p.desde or (hi - timedelta(days=180))

        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK or not dept.key:
                return department_problem(dept, p.departamento)

            # Snapshot actual
            snapshot = await _department_snapshot(db, today, dept.key)

            # Ausencias en el periodo
            periods = await absence_periods(db, lo=lo, hi=hi, department_like=dept.key, only_active=True)

            # Plantilla activa
            staff_stmt = select(Employee).where(
                Employee.active.is_(True), Employee.department_key == dept.key
            )
            staff = list((await db.scalars(staff_stmt)).all())
            headcount = len(staff)

            # ETT (opcional)
            ett_data: dict[str, Any] = {}
            if p.incluir_ett:
                ett = (await db.execute(
                    select(func.count(), func.sum(TtTimesheet.hours_total), func.sum(TtTimesheet.amount))
                    .where(TtTimesheet.department_key == dept.key, TtTimesheet.day.between(lo, hi))
                )).one()
                ett_data = {
                    "boletines": int(ett[0] or 0),
                    "horas_total": round(float(ett[1] or 0), 1),
                    "importe_total": round(float(ett[2] or 0), 2),
                }

            # Vacaciones (opcional)
            vac_data: dict[str, Any] = {}
            if p.incluir_vacaciones:
                emails = {e.email for e in staff if e.email}
                balances = list((await db.scalars(
                    select(VacationBalance).where(
                        VacationBalance.year == today.year,
                        func.lower(VacationBalance.employee_email).in_({m.lower() for m in emails}),
                    )
                )).all())
                valid_balances = [b.current_balance for b in balances if b.current_balance is not None]
                vac_data = {
                    "saldo_medio": round(sum(valid_balances) / len(valid_balances), 1) if valid_balances else None,
                    "con_saldo_negativo": sum(1 for v in valid_balances if v < 0),
                }

        # ── Estadísticas de ausencias
        by_kind: Counter[str] = Counter(ap.kind for ap in periods)
        total_days = sum(ap.days_within(lo, hi) for ap in periods)
        absence_rate = round(total_days / max(headcount * (hi - lo).days, 1) * 100, 2) if headcount > 0 else 0

        # Tendencia mensual de ausencias en el periodo
        months_covered = _months_between(lo, hi)
        monthly_abs: dict[str, int] = defaultdict(int)
        for ap in periods:
            for y, m in months_covered:
                d_in = ap.days_within(date(y, m, 1), _month_end(y, m))
                if d_in > 0:
                    monthly_abs[f"{y}-{m:02d}"] += d_in

        month_labels = [f"{y}-{m:02d}" for y, m in months_covered]
        ts_points = [TimePoint(label=lbl, value=float(monthly_abs.get(lbl, 0))) for lbl in month_labels]
        ts_stats = time_series_stats(ts_points) if len(ts_points) >= 2 else {}

        # Insights automáticos
        insights: list[Insight] = []
        if len(ts_points) >= 3:
            insights = _insight_engine.from_time_series(ts_points, label="absentismo", unit="días")

        # Outliers por persona (quiénes más días de ausencia)
        person_days: dict[str, int] = defaultdict(int)
        for ap in periods:
            person_days[ap.name] = person_days[ap.name] + ap.days_within(lo, hi)

        top_absent = sorted(person_days.items(), key=lambda x: -x[1])[:5]

        # ── Construcción de respuesta
        summary: dict[str, Any] = {
            "departamento": dept.name,
            "periodo_analizado": f"{lo.isoformat()} — {hi.isoformat()}",
            "plantilla_activa": headcount,
            "kpis_hoy": {
                "trabajando": snapshot.get("trabajando"),
                "ausentes": sum(snapshot.get("ausentes_por_tipo", {}).values()),
                "horas_programadas": snapshot.get("horas_programadas"),
                "solicitudes_vacaciones_pendientes": snapshot.get("solicitudes_pendientes"),
            },
            "ausencias_en_periodo": {
                "total_dias": total_days,
                "tasa_absentismo_pct": absence_rate,
                "por_tipo": dict(by_kind),
                "personas_distintas": len({ap.person_key for ap in periods if ap.person_key}),
            },
        }
        if vac_data:
            summary["vacaciones"] = vac_data
        if ett_data:
            summary["ett_en_periodo"] = ett_data
        if top_absent and p.profundidad == "completo":
            summary["personas_con_mas_ausencias"] = [
                {"nombre": n, "dias": d} for n, d in top_absent
            ]
        if insights and p.profundidad == "completo":
            summary["insights"] = _insight_engine.top_insights(insights, n=4)
        if ts_stats.get("trend") and p.profundidad == "completo":
            summary["tendencia_absentismo"] = ts_stats["trend"]

        # ── Presentación
        kpi_rows = [
            ["Plantilla activa", headcount],
            ["Trabajando hoy", snapshot.get("trabajando")],
            ["Horas programadas hoy", snapshot.get("horas_programadas")],
            ["Total días ausencia en periodo", total_days],
            ["Tasa absentismo (%)", f"{absence_rate}%"],
            ["Personas distintas ausentes", len({ap.person_key for ap in periods if ap.person_key})],
        ]
        for kind, cnt in sorted(by_kind.items()):
            kpi_rows.append([f"  · {kind}", cnt])
        if vac_data.get("saldo_medio") is not None:
            kpi_rows.append(["Saldo medio de vacaciones (días)", vac_data["saldo_medio"]])
        if ett_data.get("horas_total"):
            kpi_rows.append(["Horas ETT en periodo", ett_data["horas_total"]])

        tables = [table(f"Análisis · {dept.name}", ["Indicador", "Valor"], kpi_rows)]

        if top_absent and p.profundidad == "completo":
            tables.append(table(
                "Personas con más ausencias",
                ["Nombre", "Días"],
                [[n, d] for n, d in top_absent],
            ))

        # Serie temporal de ausencias
        chart = None
        if ts_points and len(ts_points) >= 2:
            labels = [p.label for p in ts_points]
            values = [monthly_abs.get(p.label, 0) for p in ts_points]
            chart = {
                "type": "line",
                "title": f"Evolución de ausencias · {dept.name}",
                "labels": labels,
                "series": [{"name": "Días de ausencia", "values": values}],
            }

        presentation: dict[str, Any] = {
            "type": "dashboard",
            "title": f"Análisis · {dept.name}",
            "tables": tables,
        }
        if chart:
            presentation["charts"] = [chart]

        return ToolResult(ToolStatus.OK, summary, presentation, {"foco_departamento": dept.name})

    return Tool(
        "analizar_departamento",
        "Análisis integral de un departamento: plantilla actual, ausencias en el periodo (distribución, "
        "tasa de absentismo, tendencia, personas más ausentes), saldos de vacaciones e insights automáticos. "
        "Responde «¿qué está pasando con Cocina?», «analiza Recepción», «¿cómo está el equipo de Pisos?». "
        "También acepta un periodo personalizado (desde/hasta). Use 'resumen' para respuestas cortas.",
        AnalizarParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        timeout_seconds=30,
    )


# ─────────────────────────────────────────────────────────────────────────────
# tendencia_metrica
# ─────────────────────────────────────────────────────────────────────────────
Metrica = Literal[
    "ausencias_totales",
    "bajas",
    "vacaciones",
    "permisos",
    "plantilla_activa",
    "ett_horas",
    "ett_importe",
]

METRICA_LABELS: dict[str, str] = {
    "ausencias_totales": "Días ausencia total",
    "bajas": "Días de baja (IT)",
    "vacaciones": "Días de vacaciones",
    "permisos": "Días de permiso",
    "plantilla_activa": "Plantilla activa",
    "ett_horas": "Horas ETT",
    "ett_importe": "Importe ETT (€)",
}


class TendenciaMetricaParams(BaseModel):
    metrica: Metrica = Field(description="Métrica a analizar")
    departamento: str | None = Field(default=None, description="Filtrar por departamento (sin valor: toda la empresa)")
    desde: date | None = Field(default=None, description="Mes inicial AAAA-MM-01 (por defecto hace 12 meses)")
    hasta: date | None = Field(default=None, description="Mes final (por defecto: mes actual)")
    granularidad: Literal["mensual", "trimestral"] = Field(default="mensual")
    comparar_con_anio_anterior: bool = Field(
        default=False,
        description="Si True, añade la serie del año anterior en el mismo gráfico para comparar YoY",
    )


def tendencia_metrica(deps: Deps) -> Tool:
    """Evolución mensual de cualquier métrica de RRHH con insights automáticos."""

    async def handler(p: TendenciaMetricaParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        hi = p.hasta or today
        lo = p.desde or _subtract_months(hi, 12)

        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)

            data = await _fetch_metric_series(deps, db, p.metrica, lo, hi, dept.key)
            prev_data: list[tuple[str, float]] = []
            if p.comparar_con_anio_anterior:
                prev_hi = _subtract_months(hi, 12)
                prev_lo = _subtract_months(lo, 12)
                prev_data = await _fetch_metric_series(deps, db, p.metrica, prev_lo, prev_hi, dept.key)

        # Aggregate by granularity
        if p.granularidad == "trimestral":
            data = _aggregate_quarterly(data)
            prev_data = _aggregate_quarterly(prev_data) if prev_data else []

        labels = [label for label, _ in data]
        values = [v for _, v in data]
        ts_points = [TimePoint(label=lbl, value=v) for lbl, v in data]
        ts_stats = time_series_stats(ts_points) if len(ts_points) >= 2 else {}
        insights = _insight_engine.from_time_series(ts_points, label=METRICA_LABELS.get(p.metrica, p.metrica))

        table_rows = [[lbl, round(v, 2)] for lbl, v in data]
        if prev_data:
            # Align prev_data labels to current labels for comparison
            prev_dict = dict(prev_data)
            for i, (lbl, v) in enumerate(data):
                prev_lbl = _shift_label_year(lbl, -1)
                table_rows[i] = [lbl, round(v, 2), round(prev_dict.get(prev_lbl, 0), 2)]

        cols = [p.granularidad.capitalize(), METRICA_LABELS.get(p.metrica, p.metrica)]
        if prev_data:
            cols.append("Año anterior")

        chart_series = [{"name": "Año actual", "values": values}]
        if prev_data:
            chart_series.append({"name": "Año anterior", "values": [v for _, v in prev_data]})

        chart = {
            "type": "line",
            "title": f"Tendencia · {METRICA_LABELS.get(p.metrica, p.metrica)} · {dept.name or 'Empresa'}",
            "labels": labels,
            "series": chart_series,
        } if labels else None

        summary: dict[str, Any] = {
            "metrica": METRICA_LABELS.get(p.metrica, p.metrica),
            "ambito": dept.name or "toda la empresa",
            "periodo": f"{lo.isoformat()} — {hi.isoformat()}",
            "granularidad": p.granularidad,
            "total": round(sum(values), 2),
            "datos": {lbl: round(v, 2) for lbl, v in data},
        }
        if ts_stats.get("trend"):
            summary["tendencia"] = ts_stats["trend"]
        if ts_stats.get("total_change"):
            summary["variacion_periodo"] = ts_stats["total_change"]
        if insights:
            summary["insights"] = _insight_engine.top_insights(insights, n=3)

        pres: dict[str, Any] = {
            "type": "table",
            "title": f"Tendencia de {METRICA_LABELS.get(p.metrica, p.metrica)}",
            "columns": cols,
            "rows": table_rows,
        }
        if chart:
            pres = {"type": "table_with_chart", "table": pres, "chart": chart}

        return ToolResult(ToolStatus.OK, summary, pres)

    return Tool(
        "tendencia_metrica",
        "Serie temporal mensual (o trimestral) de cualquier métrica de RRHH: ausencias totales, bajas, "
        "vacaciones, permisos, plantilla activa, horas/importe ETT. Opcionalmente compara con el año anterior. "
        "Responde «¿cómo han evolucionado las bajas este año?», «tendencia de absentismo en Cocina», "
        "«¿ha aumentado el uso de ETT comparado con el año pasado?».",
        TendenciaMetricaParams,
        handler,
        permission=Permission.TURNOS_LEER,
        timeout_seconds=30,
    )


# ─────────────────────────────────────────────────────────────────────────────
# comparar_universal
# ─────────────────────────────────────────────────────────────────────────────
class CompararUniversalParams(BaseModel):
    entidades: list[str] = Field(
        min_length=2,
        max_length=10,
        description="Lista de entidades a comparar: nombres de departamentos (2–10)",
    )
    metricas: list[Metrica] = Field(
        default=["ausencias_totales", "plantilla_activa"],
        description="Métricas a comparar",
    )
    desde: date | None = Field(default=None, description="Inicio del periodo (por defecto hace 3 meses)")
    hasta: date | None = Field(default=None, description="Fin del periodo (por defecto hoy)")


def comparar_universal(deps: Deps) -> Tool:
    """Compara N departamentos en N métricas, con insights automáticos."""

    async def handler(p: CompararUniversalParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        hi = p.hasta or today
        lo = p.desde or _subtract_months(hi, 3)

        # Resolve all depts
        async with deps.db.session() as db:
            dept_keys: dict[str, str] = {}
            dept_names: dict[str, str] = {}
            for name in p.entidades:
                dept = await resolve_department(db, name)
                if dept.status is not ToolStatus.OK or not dept.key:
                    return department_problem(dept, name)
                dept_keys[name] = dept.key
                dept_names[name] = dept.name or name

            # Gather data per entity × metric
            results: dict[str, dict[str, float]] = {dn: {} for dn in dept_names.values()}
            for orig_name, dname in dept_names.items():
                dkey = dept_keys[orig_name]
                for metric in p.metricas:
                    series = await _fetch_metric_series(deps, db, metric, lo, hi, dkey)
                    results[dname][METRICA_LABELS.get(metric, metric)] = round(sum(v for _, v in series), 2)

        # Build comparison table
        metric_labels = [METRICA_LABELS.get(m, m) for m in p.metricas]
        group_names = list(results.keys())
        cols = ["Métrica", *group_names, "Mejor"]
        rows_out: list[list[Any]] = []
        for mlabel in metric_labels:
            row: list[Any] = [mlabel]
            vals = [(g, results[g].get(mlabel)) for g in group_names]
            for _, v in vals:
                row.append(v if v is not None else "—")
            # Best (lower is better for absences, higher for headcount)
            valid_vals = [(g, v) for g, v in vals if v is not None]
            if valid_vals:
                if "ausencia" in mlabel.lower() or "baja" in mlabel.lower() or "ett" in mlabel.lower():
                    best = min(valid_vals, key=lambda x: x[1])[0]
                else:
                    best = max(valid_vals, key=lambda x: x[1])[0]
            else:
                best = "—"
            row.append(best)
            rows_out.append(row)

        # Insights from distribution of first metric
        first_metric = metric_labels[0] if metric_labels else None
        insights_out: list[dict[str, Any]] = []
        if first_metric:
            dist = {g: results[g].get(first_metric, 0) for g in group_names}
            ins = _insight_engine.from_distribution(dist, label="departamento", metric=first_metric)
            insights_out = _insight_engine.top_insights(ins, n=3)

        summary: dict[str, Any] = {
            "periodo": f"{lo.isoformat()} — {hi.isoformat()}",
            "entidades": group_names,
            "metricas": metric_labels,
            "datos": results,
            "insights": insights_out,
        }
        pres = table(
            f"Comparativa · {' vs '.join(group_names[:4])}",
            cols,
            rows_out,
        )
        return ToolResult(ToolStatus.OK, summary, pres)

    return Tool(
        "comparar_universal",
        "Compara 2–10 departamentos sobre múltiples métricas (ausencias, bajas, vacaciones, plantilla, ETT) "
        "en un periodo, identificando el mejor y el peor en cada métrica con insights automáticos. "
        "Responde «compara Cocina, Recepción y Pisos por absentismo y ETT», «qué departamentos van peor en bajas». "
        "Para comparaciones de un solo día usa comparar_departamentos.",
        CompararUniversalParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        timeout_seconds=45,
    )


# ─────────────────────────────────────────────────────────────────────────────
# distribucion_plantilla
# ─────────────────────────────────────────────────────────────────────────────
Dimension = Literal["departamento", "puesto", "franja_edad", "departamento_puesto"]


class DistribucionParams(BaseModel):
    por: Dimension = Field(default="departamento", description="Dimensión de agrupación")
    activos_solo: bool = Field(default=True, description="Solo empleados activos (por defecto sí)")
    departamento: str | None = Field(default=None, description="Filtrar por departamento (cuando por=puesto)")


def distribucion_plantilla(deps: Deps) -> Tool:
    """Distribución de la plantilla por departamento, puesto o franja de edad."""

    async def handler(p: DistribucionParams, ctx: ToolContext) -> ToolResult:
        from mia.modules.rrhh.empleados.tools import age  # noqa: PLC0415

        today = ctx.now.date()

        async with deps.db.session() as db:
            stmt = select(Employee)
            if p.activos_solo:
                stmt = stmt.where(Employee.active.is_(True))
            if p.departamento:
                dept = await resolve_department(db, p.departamento)
                if dept.status is not ToolStatus.OK:
                    return department_problem(dept, p.departamento)
                if dept.key:
                    stmt = stmt.where(Employee.department_key == dept.key)
            staff = list((await db.scalars(stmt)).all())

        if p.por == "departamento":
            groups: Counter[str] = Counter(e.department or "Sin dato" for e in staff)
        elif p.por == "puesto":
            groups = Counter(e.position or "Sin dato" for e in staff)
        elif p.por == "franja_edad":
            groups = Counter()
            for e in staff:
                a = age(e.birth_date, today)
                if a is None:
                    groups["Sin edad"] += 1
                elif a < 30:
                    groups["< 30"] += 1
                elif a < 40:
                    groups["30–39"] += 1
                elif a < 50:
                    groups["40–49"] += 1
                elif a < 60:
                    groups["50–59"] += 1
                else:
                    groups["60+"] += 1
        else:  # departamento_puesto
            groups = Counter(f"{e.department} · {e.position or 'Sin puesto'}" for e in staff)

        total = sum(groups.values())
        items = sorted(groups.items(), key=lambda x: -x[1])
        rows = [[k, v, f"{round(v/total*100, 1)}%"] for k, v in items]
        insights_raw = _insight_engine.from_distribution(
            {k: float(v) for k, v in items}, label=p.por.replace("_", " "), metric="personas"
        )
        ins_out = _insight_engine.top_insights(insights_raw, n=3)

        chart = {
            "type": "donut" if len(items) <= 8 else "bar",
            "title": f"Distribución por {p.por.replace('_', ' ')}",
            "labels": [k for k, _ in items],
            "series": [{"name": "Personas", "values": [float(v) for _, v in items]}],
        }

        summary: dict[str, Any] = {
            "dimension": p.por,
            "total": total,
            "grupos": len(items),
            "distribucion": {k: v for k, v in items},
            "insights": ins_out,
        }
        pres: dict[str, Any] = {
            "type": "table",
            "title": f"Plantilla por {p.por.replace('_', ' ')}",
            "columns": [p.por.replace("_", " ").capitalize(), "Personas", "% del total"],
            "rows": rows,
            "chart": chart,
        }
        return ToolResult(ToolStatus.OK, summary, pres)

    return Tool(
        "distribucion_plantilla",
        "Distribución de la plantilla activa por departamento, puesto o franja de edad, con porcentajes "
        "e insights automáticos. Responde «¿cuántos hay por departamento?», «distribución por puesto en Cocina», "
        "«¿qué franja de edad predomina?».",
        DistribucionParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# helpers internos
# ─────────────────────────────────────────────────────────────────────────────
def _months_between(lo: date, hi: date) -> list[tuple[int, int]]:
    months = []
    y, m = lo.year, lo.month
    while (y, m) <= (hi.year, hi.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _subtract_months(d: date, months: int) -> date:
    m = d.month - months
    y = d.year
    while m <= 0:
        m += 12
        y -= 1
    try:
        return date(y, m, d.day)
    except ValueError:
        return _month_end(y, m)


async def _fetch_metric_series(
    deps: Deps,
    db: Any,
    metrica: str,
    lo: date,
    hi: date,
    dept_key: str | None,
) -> list[tuple[str, float]]:
    """Devuelve [(label_mes, valor)] para la métrica en el rango dado."""
    months = _months_between(lo, hi)
    result = []

    if metrica == "plantilla_activa":
        # Empleados activos — snapshot del primer día de cada mes
        for y, m in months:
            snap = await _department_snapshot(db, date(y, m, 1), dept_key)
            result.append((f"{y}-{m:02d}", float(snap.get("plantilla_activa", 0))))
        return result

    if metrica in ("ett_horas", "ett_importe"):
        col = TtTimesheet.hours_total if metrica == "ett_horas" else TtTimesheet.amount
        for y, m in months:
            start_m = date(y, m, 1)
            end_m = _month_end(y, m)
            q = select(func.sum(col)).where(TtTimesheet.day.between(start_m, end_m))
            if dept_key:
                q = q.where(TtTimesheet.department_key == dept_key)
            val = (await db.scalar(q)) or 0
            result.append((f"{y}-{m:02d}", float(val)))
        return result

    # Ausencias (bajas, vacaciones, permisos, total)
    kind_filter = {
        "bajas": ShiftKind.BAJA,
        "vacaciones": ShiftKind.VACACIONES,
        "permisos": ShiftKind.PERMISO,
    }.get(metrica)

    stmt = select(ShiftDay).where(ShiftDay.day.between(lo, hi))
    if dept_key:
        stmt = stmt.where(ShiftDay.department_key.like(f"%{dept_key}%"))
    if kind_filter:
        stmt = stmt.where(ShiftDay.kind == kind_filter)
    elif metrica == "ausencias_totales":
        stmt = stmt.where(ShiftDay.kind.in_(ABSENT_KINDS))
    else:
        return []
    all_days = list((await db.scalars(stmt)).all())
    by_month: Counter[str] = Counter()
    for d in all_days:
        key = f"{d.day.year}-{d.day.month:02d}"
        by_month[key] += 1
    return [(f"{y}-{m:02d}", float(by_month.get(f"{y}-{m:02d}", 0))) for y, m in months]


def _aggregate_quarterly(data: list[tuple[str, float]]) -> list[tuple[str, float]]:
    q_totals: dict[str, float] = defaultdict(float)
    q_order: list[str] = []
    for label, v in data:
        try:
            y, m = int(label[:4]), int(label[5:7])
            q = (m - 1) // 3 + 1
            qkey = f"Q{q} {y}"
            if qkey not in q_totals:
                q_order.append(qkey)
            q_totals[qkey] += v
        except (ValueError, IndexError):
            pass
    return [(k, q_totals[k]) for k in q_order]


def _shift_label_year(label: str, delta: int) -> str:
    try:
        y, m = int(label[:4]), label[4:]
        return f"{y + delta}{m}"
    except ValueError:
        return label


# ─────────────────────────────────────────────────────────────────────────────
# register
# ─────────────────────────────────────────────────────────────────────────────
def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(analizar_departamento(deps))
    registry.register(tendencia_metrica(deps))
    registry.register(comparar_universal(deps))
    registry.register(distribucion_plantilla(deps))
