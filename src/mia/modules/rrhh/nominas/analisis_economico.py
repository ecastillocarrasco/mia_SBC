"""Análisis económico de nóminas multi-periodo (NOM-005).

Resuelve expresiones temporales naturales («último trimestre», «T3 2026», «2026»…) en meses
concretos, descarga los PDFs de todos los meses EN PARALELO con un semáforo compartido y
devuelve un informe estructurado con:
  • Totales por departamento × mes y trimestral/anual.
  • Estadísticas salariales (media, mediana, mín, máx).
  • Insights automáticos (tendencia, concentración, valores atípicos).
  • Datos de gráficos listos para el frontend (donut, barras, línea).

Salvaguardas:
  * Permiso nominas:importes y auditoría.
  * MIN_GROUP = 3 personas mínimas por grupo para mostrar importes.
  * Los totales "globales" (general, por mes, KPIs, gráficos) se calculan SOLO sobre departamentos que
    superan MIN_GROUP: si incluyeran también a los grupos ocultos, restando los departamentos visibles
    (mostrados con su importe exacto) se deduciría el importe exacto del grupo protegido.
  * Importes solo en pantalla, nunca en voz alta.
  * No se almacenan importes — solo se calculan agregados.
  * Sin tope artificial de volumen: se procesan todas las nóminas del periodo (ver LARGE_VOLUME_WARNING,
    puramente informativo). Para rangos de varios miles de nóminas, un turno síncrono puede no bastar;
    no existe aún un mecanismo de trabajo en segundo plano (pendiente, ver informe de escalabilidad).
"""

from __future__ import annotations

import asyncio
from datetime import date
from statistics import mean, median
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select

from mia.analytics.insights import InsightEngine
from mia.analytics.stats import TimePoint
from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, Payslip
from mia.diagnostics import EventStage, current_call_id, current_trace
from mia.modules.rrhh.common import (
    ActivosParams,
    Deps,
    department_problem,
    population_label,
    resolve_department,
    table,
)
from mia.modules.rrhh.content import content_unavailable
from mia.modules.rrhh.nominas.estadisticas import MIN_GROUP, _amounts, format_eur
from mia.query.period import ResolvedPeriod, period_engine
from mia.text import normalize_key

_insight_engine = InsightEngine()

CONCURRENCY = 8
TIMEOUT_SECONDS = 280
LARGE_VOLUME_WARNING = 1000
"""Umbral puramente informativo: por encima, se avisa de que puede tardar, pero NUNCA se rechaza ni se
recorta el periodo. El límite real es el tiempo (TIMEOUT_SECONDS) o, si no cabe en un turno, la ausencia
de un mecanismo de trabajo en segundo plano — ver informe de escalabilidad."""

RULE = (
    "NOM-005: importes calculados de nóminas al momento; no se guardan. Solo agregados por grupo "
    f"(mínimo {MIN_GROUP} personas). No digas los importes en voz alta."
)

_CONCEPTO_LABEL: dict[str, str] = {
    "liquido": "Líquido (neto)",
    "devengado": "Devengado (bruto)",
    "coste_empresa": "Coste empresa",
}

_CONCEPTO_KEY: dict[str, str] = {
    "liquido": "liquido",
    "devengado": "total_devengado",
    "coste_empresa": "coste_total_empresa",
}


def _month_iter(resolved: ResolvedPeriod) -> list[str]:
    """Devuelve lista de strings AAAA-MM para todos los meses dentro del periodo."""
    months: list[str] = []
    d = resolved.start.replace(day=1)
    end = resolved.end.replace(day=1)
    while d <= end:
        months.append(d.strftime("%Y-%m"))
        month = d.month + 1
        year = d.year + (1 if month > 12 else 0)
        month = month if month <= 12 else 1
        d = d.replace(year=year, month=month)
    return months


def _fmt(v: float | None) -> str | None:
    return format_eur(v) if v is not None else None


def _pct(part: float, total: float) -> float | None:
    if not total:
        return None
    return round(part / total * 100, 1)


class AnalisisEconomicoParams(ActivosParams):
    periodo: str = Field(
        description=(
            "Expresión temporal: 'último trimestre', 'T3 2026', 'tercer trimestre', "
            "'julio-septiembre 2026', '2026-07', '2026', 'año pasado', 'últimos 3 meses'…"
        )
    )
    departamento: str | None = Field(
        default=None,
        description="Filtrar a un solo departamento (vacío = todos).",
    )
    concepto: Literal["liquido", "devengado", "coste_empresa"] = Field(
        default="liquido",
        description=(
            "Concepto económico principal: "
            "'liquido' = neto abonado al empleado, "
            "'devengado' = bruto, "
            "'coste_empresa' = devengado + cotizaciones empresa. "
            "Para 'gasto en nóminas' o 'coste salarial' usa 'coste_empresa' si hay datos, si no 'devengado'."
        ),
    )
    incluir_grupos_pequenos: bool = Field(
        default=False,
        description=(
            f"Si True, muestra importes de grupos con menos de {MIN_GROUP} personas "
            "(solo cuando el usuario lo pide explícitamente). "
            "No lo uses por defecto."
        ),
    )


async def _fetch_amounts_batch(
    deps: Deps,
    payslips: list[Payslip],
    gate: asyncio.Semaphore,
) -> dict[int, dict[str, float]]:
    """Descarga y parsea los PDFs de una lista de nóminas en paralelo."""
    results = await asyncio.gather(
        *(_amounts(deps, slip.sp_id, gate) for slip in payslips),
        return_exceptions=False,
    )
    return {slip.sp_id: r for slip, r in zip(payslips, results, strict=True) if r}


def _group_stats(values: list[float], people_count: int, hidden: bool, min_group: int) -> dict[str, Any]:
    """Estadísticas de un grupo, con salvaguarda de tamaño mínimo.

    ``hidden`` lo decide el llamador (sobre PERSONAS distintas, no sobre observaciones persona×mes: un
    grupo de 2 personas con varios meses de datos sigue siendo un grupo de 2 a efectos de NOM-005).
    """
    n = len(values)
    if hidden:
        return {
            "personas_con_nomina": n,
            "personas_del_grupo": people_count,
            "importes": f"ocultos: grupo por debajo del mínimo de {min_group} personas (protección de datos)",
        }
    if n == 0:
        return {"personas_con_nomina": 0, "personas_del_grupo": people_count, "importes": "sin datos"}
    return {
        "personas_con_nomina": n,
        "personas_del_grupo": people_count,
        "total": round(sum(values), 2),
        "media": round(mean(values), 2),
        "mediana": round(median(values), 2),
        "minimo": round(min(values), 2),
        "maximo": round(max(values), 2),
    }


def _department_summary(
    dept_total: float,
    total_visible: float,
    dept_month_values: dict[tuple[str, str], list[float]],
    dk: str,
    meses: list[str],
    all_vals: list[float],
    people_count: int,
    hidden: bool,
    min_grp: int,
) -> dict[str, Any]:
    """Resumen de un departamento para el LLM; igual que la tabla, los grupos pequeños no exponen totales
    (con solo 1-2 personas el total y el desglose mensual permiten deducir el sueldo de cada una)."""
    stats = _group_stats(all_vals, people_count, hidden, min_grp)
    if hidden:
        return stats
    return {
        "total": round(dept_total, 2),
        "peso_pct": _pct(dept_total, total_visible),
        "por_mes": {m: round(sum(dept_month_values.get((dk, m), [])), 2) or None for m in meses},
        **stats,
    }


def analisis_economico_nominas(deps: Deps) -> Tool:
    """Herramienta de análisis económico trimestral/anual de nóminas."""

    async def handler(p: AnalisisEconomicoParams, ctx: ToolContext) -> ToolResult:
        if problem := content_unavailable(deps):
            return problem

        # 1. Resolver periodo natural → lista de meses AAAA-MM
        today = ctx.now.date() if ctx.now else date.today()
        resolved: ResolvedPeriod | None = period_engine.resolve(p.periodo, today=today)
        if resolved is None:
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS,
                {"mensaje": f"No he podido interpretar el periodo «{p.periodo}». Usa expresiones como 'T3 2026', 'último trimestre', 'julio 2026', '2026'…"},
            )
        meses = _month_iter(resolved)
        if not meses:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": "El periodo no contiene meses completos."})
        if len(meses) > 24:
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS,
                {"mensaje": f"El periodo abarca {len(meses)} meses. Acota a máximo 24 meses para un análisis detallado."},
            )

        concepto_key = _CONCEPTO_KEY[p.concepto]
        concepto_label = _CONCEPTO_LABEL[p.concepto]
        min_grp = 1 if p.incluir_grupos_pequenos else MIN_GROUP

        # 2. Obtener personas y nóminas del periodo completo en UNA sola transacción BD
        async with deps.db.session() as db:
            stmt = select(Employee).where(Employee.person_key.is_not(None))
            if not p.incluir_inactivos:
                stmt = stmt.where(Employee.active.is_(True))
            if p.departamento:
                dept = await resolve_department(db, p.departamento)
                if dept.status is not ToolStatus.OK:
                    return department_problem(dept, p.departamento)
                if dept.key:
                    stmt = stmt.where(Employee.department_key == dept.key)
            stmt = stmt.order_by(Employee.sp_id)
            people: list[Employee] = list((await db.scalars(stmt)).all())

            if not people:
                return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": "No hay personas con esos criterios."})

            keys = {e.person_key for e in people}
            # Una sola query para todos los meses del periodo
            all_slips = list(
                (
                    await db.scalars(
                        select(Payslip)
                        .where(
                            Payslip.person_key.in_(keys),
                            Payslip.special.is_(False),
                            Payslip.period.in_(meses),
                        )
                        .order_by(Payslip.period.asc())
                    )
                ).all()
            )

        # Índice: (person_key, periodo) → primera nómina ordinaria encontrada
        slip_index: dict[tuple[str, str], Payslip] = {}
        for s in all_slips:
            k = (s.person_key or "", s.period or "")
            if k not in slip_index:
                slip_index[k] = s

        # 3. Descargar PDFs de todos los meses en PARALELO con semáforo compartido. Sin tope artificial:
        # se descargan TODAS las nóminas del periodo (es una suma, no una muestra estadística; un recorte
        # silencioso aquí falsearía el total). El semáforo (CONCURRENCY) acota la presión sobre SharePoint;
        # si el volumen es tan grande que no cabe en el timeout de la herramienta, el propio ToolRegistry
        # lo corta con SOURCE_UNAVAILABLE — un fallo honesto, nunca un total parcial disfrazado de completo.
        slips_to_fetch: list[Payslip] = []
        seen_slip_ids: set[int] = set()
        for mes in meses:
            for e in people:
                if e.person_key:
                    slip = slip_index.get((e.person_key, mes))
                    if slip and slip.sp_id not in seen_slip_ids:
                        slips_to_fetch.append(slip)
                        seen_slip_ids.add(slip.sp_id)

        volume_advertencia: str | None = None
        if len(slips_to_fetch) > LARGE_VOLUME_WARNING:
            volume_advertencia = (
                f"El periodo implica leer {len(slips_to_fetch)} nóminas; puede tardar varios minutos. "
                "Si el turno se agota antes de terminar, acota por departamento o por menos meses."
            )

        gate = asyncio.Semaphore(CONCURRENCY)
        amounts_by_id = await _fetch_amounts_batch(deps, slips_to_fetch, gate)

        # 4. Calcular estadísticas por departamento × mes
        # dept_key → display_name
        dept_display: dict[str, str] = {}
        # (dept_key, mes) → list[float] de valores del concepto
        dept_month_values: dict[tuple[str, str], list[float]] = {}
        # dept_key → list[float] de todos los valores del concepto (para stats trimestrales)
        dept_all_values: dict[str, list[float]] = {}
        # dept_key → count personas del grupo
        dept_people: dict[str, int] = {}
        # dept_key → person_keys distintos con al menos un importe leído en el periodo. El tamaño del
        # grupo a efectos de NOM-005 es el número de PERSONAS, no de observaciones persona×mes: un
        # departamento de 2 personas con 3 meses de datos sigue siendo un grupo de 2 (se deduciría el sueldo).
        dept_distinct_people: dict[str, set[str]] = {}
        # Nóminas leídas pero sin coste_total_empresa (sin cotizaciones SS en el PDF): nunca se sustituyen
        # por el devengado (serían magnitudes distintas mezcladas bajo la misma etiqueta); solo se cuentan
        # para avisar de la cobertura real del concepto "coste_empresa".
        coste_empresa_sin_ss = 0

        for e in people:
            if not e.person_key:
                continue
            dept_raw = e.department or "Sin departamento"
            dk = normalize_key(dept_raw)
            dept_display.setdefault(dk, dept_raw)
            dept_people[dk] = dept_people.get(dk, 0) + 1

            for mes in meses:
                slip = slip_index.get((e.person_key, mes))
                if slip and slip.sp_id in amounts_by_id:
                    amounts = amounts_by_id[slip.sp_id]
                    val = amounts.get(concepto_key)
                    if val is None and p.concepto == "coste_empresa" and "total_devengado" in amounts:
                        coste_empresa_sin_ss += 1
                    if val is not None:
                        dept_month_values.setdefault((dk, mes), []).append(val)
                        dept_all_values.setdefault(dk, []).append(val)
                        dept_distinct_people.setdefault(dk, set()).add(e.person_key)

        # 5. Departamentos y salvaguarda NOM-005 (antes de calcular ningún agregado global: los totales
        # "globales" expuestos nunca deben incluir la contribución de un grupo oculto, o restando los
        # departamentos visibles al total se deduciría exactamente el importe del grupo protegido).
        dept_totals: dict[str, float] = {}
        for dk, vals in dept_all_values.items():
            dept_totals[dk] = round(sum(vals), 2)

        dept_keys_sorted = sorted(dept_totals, key=lambda dk: -dept_totals[dk])
        hidden_keys = {dk for dk in dept_keys_sorted if len(dept_distinct_people.get(dk, ())) < min_grp}

        # Totales "globales" (mes a mes y general) calculados SOLO sobre departamentos visibles: si se
        # calcularan sobre todos y se mostrara también cada departamento visible con su importe exacto,
        # el grupo oculto quedaría expuesto por resta (total_general - suma_visibles = su importe exacto).
        month_totals: dict[str, float] = {mes: 0.0 for mes in meses}
        for dk in dept_keys_sorted:
            if dk in hidden_keys:
                continue
            for mes in meses:
                month_totals[mes] += sum(dept_month_values.get((dk, mes), []))

        meses_con_datos = [m for m in meses if month_totals.get(m, 0) > 0]
        meses_sin_datos = [m for m in meses if month_totals.get(m, 0) == 0]
        total_visible = round(sum(month_totals.values()), 2)

        # Metadatos de integridad temporal para el diagnóstico automático (sin importes ni datos personales):
        # permite que el analizador compare el periodo pedido por el usuario con el realmente ejecutado y
        # marque TEMPORAL_SCOPE_MISMATCH si, p. ej., se pidió un trimestre y solo se resolvió un mes.
        if trace := current_trace():
            trace.emit(
                EventStage.DATA_AGGREGATION,
                data={
                    "tool": "analisis_economico_nominas",
                    "periodo_solicitado": p.periodo,
                    "periodo_interpretado": resolved.label,
                    "meses_resueltos": len(meses),
                    "meses_con_datos": len(meses_con_datos),
                    "departamentos_incluidos": len(dept_keys_sorted),
                },
                call_id=current_call_id(),
            )

        # Columnas de la tabla: Dept | mes1 | mes2 | ... | Total | Peso%
        mes_labels = [_mes_label(m) for m in meses]
        table_cols = ["Departamento"] + mes_labels + ["Total", "Peso %"]
        table_rows: list[list[Any]] = []

        for dk in dept_keys_sorted:
            display = dept_display.get(dk, dk)
            total_dk = dept_totals.get(dk, 0.0)

            if dk in hidden_keys:
                row_vals = ["—" for _ in meses]
                row = [display] + row_vals + ["—", "—"]
            else:
                row_vals = []
                for mes in meses:
                    m_vals = dept_month_values.get((dk, mes), [])
                    if not m_vals:
                        row_vals.append("—")
                    else:
                        row_vals.append(_fmt(round(sum(m_vals), 2)))
                peso = _pct(total_dk, total_visible)
                row = [display] + row_vals + [_fmt(total_dk), f"{peso:.1f}%" if peso else "—"]
            table_rows.append(row)

        # Fila TOTAL (solo departamentos visibles — ver nota de NOM-005 más arriba)
        total_row: list[Any] = ["TOTAL (autorizado)" if hidden_keys else "TOTAL"]
        for mes in meses:
            mt = month_totals.get(mes)
            total_row.append(_fmt(round(mt, 2)) if mt else "—")
        total_row += [_fmt(total_visible), "100%"]
        table_rows.append(total_row)

        # 6. Tabla estadísticas salariales por departamento
        stats_cols = ["Departamento", "Personas", "Media", "Mediana", "Mínimo", "Máximo"]
        stats_rows: list[list[Any]] = []
        for dk in dept_keys_sorted:
            display = dept_display.get(dk, dk)
            all_vals = dept_all_values.get(dk, [])
            grp = _group_stats(all_vals, dept_people.get(dk, 0), dk in hidden_keys, min_grp)
            if "total" in grp:
                stats_rows.append([
                    display,
                    grp["personas_con_nomina"],
                    _fmt(grp.get("media")),
                    _fmt(grp.get("mediana")),
                    _fmt(grp.get("minimo")),
                    _fmt(grp.get("maximo")),
                ])
            else:
                stats_rows.append([display, grp.get("personas_del_grupo", 0), grp.get("importes", "—"), "—", "—", "—"])

        # 7. Insights automáticos
        # 7a. Distribución por departamento
        dist_groups = {
            dept_display.get(dk, dk): dept_totals[dk]
            for dk in dept_keys_sorted
            if dk not in hidden_keys
        }
        dist_insights = _insight_engine.from_distribution(
            dist_groups,
            label="departamento",
            metric="gasto salarial trimestral",
            unit="€",
        ) if dist_groups else []

        # 7b. Evolución temporal (solo si hay ≥2 meses con datos)
        ts_points = [
            TimePoint(label=_mes_label(m), value=round(month_totals.get(m, 0.0), 2))
            for m in meses
        ]
        ts_insights = _insight_engine.from_time_series(
            ts_points,
            label="gasto salarial",
            unit="€",
        ) if len(meses_con_datos) >= 2 else []

        all_insights = _insight_engine.top_insights(dist_insights + ts_insights, n=6)

        # 8. Datos de gráficos para el frontend
        # 8a. Donut: distribución del gasto por departamento
        depts_with_data = [dk for dk in dept_keys_sorted if dk not in hidden_keys]
        donut_chart = {
            "type": "donut",
            "title": f"Distribución del gasto · {resolved.label}",
            "labels": [dept_display.get(dk, dk) for dk in depts_with_data],
            "series": [{"name": concepto_label, "values": [dept_totals[dk] for dk in depts_with_data]}],
        } if depts_with_data else None

        # 8b. Barras horizontales: ranking por coste total
        bar_chart = {
            "type": "bar",
            "title": f"Ranking de gasto salarial · {resolved.label}",
            "labels": [dept_display.get(dk, dk) for dk in depts_with_data],
            "series": [{"name": concepto_label, "values": [dept_totals[dk] for dk in depts_with_data]}],
        } if depts_with_data else None

        # 8c. Línea: evolución mensual del gasto total
        line_chart = {
            "type": "line",
            "title": "Evolución mensual del gasto salarial",
            "labels": [_mes_label(m) for m in meses],
            "series": [{"name": concepto_label, "values": [round(month_totals.get(m, 0.0), 2) for m in meses]}],
        } if len(meses) >= 2 else None

        charts = [c for c in [donut_chart, bar_chart, line_chart] if c is not None]

        # 9. Variaciones mes a mes
        variaciones: list[dict[str, Any]] = []
        for i in range(1, len(meses)):
            prev, curr = meses[i - 1], meses[i]
            t_prev = month_totals.get(prev, 0.0)
            t_curr = month_totals.get(curr, 0.0)
            if t_prev > 0:
                diff_pct = round((t_curr - t_prev) / t_prev * 100, 1)
                variaciones.append({
                    "de": _mes_label(prev),
                    "a": _mes_label(curr),
                    "variacion_eur": round(t_curr - t_prev, 2),
                    "variacion_pct": diff_pct,
                })

        # 10. KPIs
        kpis: list[dict[str, Any]] = [
            {
                "label": "Gasto total del periodo (grupos autorizados)" if hidden_keys else "Gasto total del periodo",
                "value": _fmt(total_visible),
                "highlight": True,
            },
        ]
        for mes in meses_con_datos:
            kpis.append({"label": _mes_label(mes), "value": _fmt(round(month_totals.get(mes, 0.0), 2))})
        if variaciones:
            last_var = variaciones[-1]
            sign = "+" if last_var["variacion_pct"] >= 0 else ""
            kpis.append({"label": f"Var. {last_var['de']} → {last_var['a']}", "value": f"{sign}{last_var['variacion_pct']}%"})
        if depts_with_data:
            dk_top = depts_with_data[0]
            kpis.append({"label": "Mayor gasto", "value": dept_display.get(dk_top, dk_top)})

        # 11. Advertencias
        advertencias: list[str] = []
        if volume_advertencia:
            advertencias.append(volume_advertencia)
        if meses_sin_datos:
            advertencias.append(
                f"Sin datos para: {', '.join(_mes_label(m) for m in meses_sin_datos)}. "
                "El análisis es parcial."
            )
        if len(meses_con_datos) < len(meses):
            advertencias.append("El periodo está incompleto: no se muestran totales como si fuera un trimestre completo.")
        if hidden_keys:
            advertencias.append(
                f"{len(hidden_keys)} departamento(s) no cumplen el mínimo de {min_grp} personas y no se "
                "desglosan (protección de datos, NOM-005). El total general y los porcentajes excluyen esos "
                "grupos: NO representan el 100% de la nómina de la empresa, solo los grupos autorizados a "
                "mostrarse. No se puede deducir su importe por resta porque no se expone el total real de "
                "toda la empresa junto al de los grupos visibles."
            )
        if p.concepto == "coste_empresa" and coste_empresa_sin_ss:
            advertencias.append(
                f"{coste_empresa_sin_ss} nómina(s) leída(s) no incluían cotizaciones de empresa (SS) en el "
                "PDF: no se cuentan como coste_empresa (nunca se sustituyen por el devengado, son magnitudes "
                "distintas). El total de coste_empresa puede estar incompleto para esas nóminas."
            )

        # 12. Summary para el LLM
        summary: dict[str, Any] = {
            "periodo_interpretado": resolved.label,
            "meses_analizados": meses,
            "meses_con_datos": meses_con_datos,
            "meses_sin_datos": meses_sin_datos if meses_sin_datos else None,
            "concepto_economico": concepto_label,
            "poblacion": population_label(p.incluir_inactivos),
            "personas_del_grupo": len(people),
            "total_periodo": total_visible,
            "total_periodo_es_solo_grupos_autorizados": bool(hidden_keys),
            "total_por_mes": {m: round(month_totals.get(m, 0.0), 2) for m in meses},
            "variaciones": variaciones if variaciones else None,
            "por_departamento": {
                dept_display.get(dk, dk): _department_summary(
                    dept_totals.get(dk, 0.0),
                    total_visible,
                    dept_month_values,
                    dk,
                    meses,
                    dept_all_values.get(dk, []),
                    dept_people.get(dk, 0),
                    dk in hidden_keys,
                    min_grp,
                )
                for dk in dept_keys_sorted
            },
            "insights": all_insights,
            "advertencias": advertencias if advertencias else None,
            "regla": RULE,
        }

        # 13. Construir las presentaciones
        status = ToolStatus.OK if meses_con_datos else ToolStatus.NOT_FOUND

        stats_table = table(
            f"Estadísticas salariales · {resolved.label} ({concepto_label})",
            stats_cols,
            stats_rows,
        )
        main_table = table(
            f"Gasto salarial por departamento · {resolved.label} ({concepto_label})",
            table_cols,
            table_rows,
            charts=charts,
            kpis=kpis,
            stats=stats_table,
        )

        return ToolResult(status, summary, main_table)

    return Tool(
        "analisis_economico_nominas",
        (
            "Análisis económico completo de nóminas para un periodo: trimestre, año, varios meses o comparativa. "
            "Resuelve automáticamente expresiones como 'último trimestre', 'T3 2026', 'primer trimestre de 2026', "
            "'últimos 6 meses', '2026', 'julio-septiembre'… "
            "Devuelve totales por departamento y mes, desglose mensual, evolución, estadísticas salariales, "
            "insights económicos y gráficos. "
            "Usa 'coste_empresa' cuando el usuario pregunte por 'gasto en nóminas' o 'coste salarial'. "
            "Para consultas de un solo mes, esta herramienta también funciona (p. ej. periodo='septiembre 2026'). "
            "Para comparativas entre periodos distintos, llámala dos veces con periodos diferentes. "
            "Esta es la herramienta correcta para cualquier 'comparativa de costes/nóminas por "
            "departamento': después de ejecutarla, usa 'generar_informe' para exportar el resultado a "
            "PDF/Excel/PowerPoint/HTML — nunca 'generar_informe_ejecutivo', que no calcula importes."
        ),
        AnalisisEconomicoParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=TIMEOUT_SECONDS,
    )


# ------------------------------------------------------------------ helpers
def _mes_label(periodo: str) -> str:
    """'2026-07' → 'Jul 26'."""
    try:
        parts = periodo.split("-")
        month_abbr = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        m = int(parts[1])
        y = parts[0][2:]
        return f"{month_abbr[m]} {y}"
    except Exception:
        return periodo
