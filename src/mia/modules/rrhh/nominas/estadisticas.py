"""Estadísticas salariales agregadas (NOM-004).

«¿Cuál es el salario medio de un cocinero?», «líquido medio por departamento». Se leen las nóminas de la
plantilla activa del grupo en el momento y solo se devuelven agregados: media, mediana, mínimo y máximo.
Salvaguardas:
  * permiso propio (nominas:importes) y auditoría;
  * mínimo de personas por grupo: por debajo no se muestran importes (evita deducir el sueldo de alguien);
  * nunca se devuelve ni se cita el importe de una persona concreta;
  * los importes no se dicen en voz alta (filtro en código);
  * no se persisten en disco ni en base de datos. Sí existe una caché EN MEMORIA del proceso, de corta
    duración (``_AMOUNTS_CACHE_TTL``), para no releer el mismo PDF en consultas repetidas o solapadas
    sobre el mismo periodo; se pierde al reiniciar el servicio y nunca se escribe en ningún almacén.
"""

from __future__ import annotations

import asyncio
import time
from statistics import mean, median, quantiles
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, Payslip
from mia.modules.rrhh.common import (
    ActivosParams,
    Deps,
    department_problem,
    population_label,
    resolve_department,
    table,
)
from mia.modules.rrhh.content import MAX_BYTES, content_unavailable, pdf_lines
from mia.modules.rrhh.nominas.parser import parse_payslip
from mia.text import normalize_key

MIN_GROUP = 3
"""Personas mínimas por grupo para mostrar un importe agregado."""
MAX_PEOPLE = 150
MAX_RANKING = 10
MAX_RANKING_GROUP = 200
CONCURRENCY = 8
RULE = (
    "NOM-004: importes agregados leídos de las nóminas en el momento; no se guardan. Nunca se muestra el "
    f"importe de una persona, y no se muestran grupos de menos de {MIN_GROUP} personas. No los digas en voz alta."
)


class SalarialesParams(ActivosParams):
    puesto: str | None = Field(default=None, description="Parte del puesto: «cocinero», «camarera de pisos»…")
    departamento: str | None = None
    periodo: str | None = Field(default=None, description="AAAA-MM; por defecto la última nómina ordinaria de cada uno")
    agrupar_por: Literal["puesto", "departamento", "ninguno"] = Field(
        default="ninguno", description=f"Desglosar por puesto o por departamento (cada grupo debe tener {MIN_GROUP}+ personas)"
    )


def format_eur(value: float) -> str:
    """2200.12 → «2.200,12 €» (formato español, para pantalla)."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _stats(values: list[float]) -> dict[str, float]:
    out: dict[str, float] = {
        "suma": round(sum(values), 2),
        "media": round(mean(values), 2),
        "mediana": round(median(values), 2),
        "minimo": round(min(values), 2),
        "maximo": round(max(values), 2),
    }
    if len(values) >= 4:
        q = quantiles(values, n=4)
        out["percentil_25"] = round(q[0], 2)
        out["percentil_75"] = round(q[2], 2)
    return out


_AMOUNTS_CACHE: dict[tuple[int, int], tuple[float, dict[str, float] | None]] = {}
_AMOUNTS_CACHE_TTL = 1200.0  # 20 min: evita releer el mismo PDF en consultas repetidas o solapadas
_AMOUNTS_CACHE_MAXSIZE = 20_000


def _clear_amounts_cache() -> None:
    """Solo para aislar pruebas entre sí (claves por id() del cliente SharePoint de cada fixture).
    En producción el caché vive mientras viva el proceso; nunca se expone fuera de este módulo."""
    _AMOUNTS_CACHE.clear()


async def _amounts(deps: Deps, slip_id: int, gate: asyncio.Semaphore) -> dict[str, float] | None:
    # Clave por (cliente SharePoint, slip_id): en producción hay un único cliente de larga vida, así que
    # equivale a cachear solo por slip_id; en pruebas, cada fixture crea su propio cliente, así que sus
    # cachés no se mezclan aunque reutilicen los mismos ids numéricos pequeños.
    key = (id(deps.sharepoint), slip_id)
    now = time.monotonic()
    cached = _AMOUNTS_CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    async with gate:
        try:
            content = await deps.sharepoint.download_item_file("Nominas", slip_id, MAX_BYTES)
            full = parse_payslip(pdf_lines(content))
            parsed = full.get("importes") or {}
        except Exception:  # un PDF ilegible no invalida el conjunto: se cuenta como no leído
            result = None
        else:
            result = {k: parsed[k] for k in ("total_devengado", "liquido") if parsed.get(k)}
            if ss_total := (full.get("coste_empresa") or {}).get("total_aportacion_empresa"):
                devengado = parsed.get("total_devengado")
                result["coste_empresa_ss"] = ss_total
                if devengado:
                    result["coste_total_empresa"] = round(devengado + ss_total, 2)
            result = result or None

    if len(_AMOUNTS_CACHE) >= _AMOUNTS_CACHE_MAXSIZE:
        _AMOUNTS_CACHE.pop(next(iter(_AMOUNTS_CACHE)))  # descarta la entrada más antigua (FIFO simple)
    _AMOUNTS_CACHE[key] = (now + _AMOUNTS_CACHE_TTL, result)
    return result


def _group_summary(members: list[dict[str, float]], total: int) -> dict[str, Any]:
    if len(members) < MIN_GROUP:
        return {
            "personas": total,
            "nominas_leidas": len(members),
            "importes": f"no se muestran: menos de {MIN_GROUP} nóminas leídas (protección de datos)",
        }
    out: dict[str, Any] = {"personas": total, "nominas_leidas": len(members)}
    for key, label in (
        ("liquido", "liquido"),
        ("total_devengado", "devengado"),
        ("coste_total_empresa", "coste_total_empresa"),
    ):
        values = [m[key] for m in members if key in m]
        if len(values) >= MIN_GROUP:
            out[label] = _stats(values)
    return out


async def _group_payslips(
    deps: Deps, p: SalarialesParams
) -> tuple[list[Employee], dict[str, Payslip], ToolResult | None]:
    """Personas del grupo y su nómina ordinaria (la del periodo pedido o la más reciente de cada una)."""
    async with deps.db.session() as db:
        stmt = select(Employee).where(Employee.person_key.is_not(None))
        if not p.incluir_inactivos:
            stmt = stmt.where(Employee.active.is_(True))
        if p.departamento:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return [], {}, department_problem(dept, p.departamento)
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
        people = [
            e
            for e in (await db.scalars(stmt)).all()
            if not p.puesto or normalize_key(p.puesto) in normalize_key(e.position)
        ]
        slips = (
            await db.scalars(
                select(Payslip)
                .where(
                    Payslip.person_key.in_({e.person_key for e in people}),
                    Payslip.special.is_(False),
                    *([Payslip.period == p.periodo] if p.periodo else []),
                )
                .order_by(Payslip.period.desc())
            )
        ).all()
    latest: dict[str, Payslip] = {}
    for s in slips:
        if s.person_key and s.person_key not in latest:
            latest[s.person_key] = s
    return people, latest, None


class RankingParams(SalarialesParams):
    orden: Literal["mayor", "menor"] = Field(default="mayor", description="«mayor» = quién cobra más")
    cuantos: int = Field(default=3, ge=1, le=MAX_RANKING, description="Cuántos mostrar (máximo 10)")
    importe: Literal["liquido", "devengado"] = "liquido"


def ranking_salarial(deps: Deps) -> Tool:
    """Quién cobra más/menos de un grupo, ordenado sobre TODAS las nóminas del grupo (nunca sobre una muestra)."""

    async def handler(p: RankingParams, ctx: ToolContext) -> ToolResult:
        if problem := content_unavailable(deps):
            return problem
        people, latest, problem_result = await _group_payslips(deps, p)
        if problem_result:
            return problem_result
        if len(people) < MIN_GROUP:
            return ToolResult(
                ToolStatus.PERMISSION_DENIED,
                {
                    "mensaje": f"El grupo tiene menos de {MIN_GROUP} personas: no se muestran importes individuales "
                    "(protección de datos).",
                    "personas_del_grupo": len(people),
                },
            )
        with_slip = [e for e in people if e.person_key in latest]
        if len(with_slip) > MAX_RANKING_GROUP:
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS,
                {
                    "mensaje": f"El grupo tiene {len(with_slip)} personas con nómina; acota por departamento o puesto "
                    f"(máximo {MAX_RANKING_GROUP}) para poder ordenar sobre todas."
                },
            )
        gate = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(*(_amounts(deps, latest[e.person_key or ""].sp_id, gate) for e in with_slip))
        key = "liquido" if p.importe == "liquido" else "total_devengado"
        read = [(e, r[key]) for e, r in zip(with_slip, results, strict=True) if r and key in r]
        ordered = sorted(read, key=lambda x: x[1], reverse=(p.orden == "mayor"))[: p.cuantos]
        summary: dict[str, Any] = {
            "poblacion": population_label(p.incluir_inactivos),
            "criterios": {
                k: v
                for k, v in {
                    "puesto": p.puesto,
                    "departamento": p.departamento,
                    "periodo": p.periodo or "última nómina ordinaria",
                }.items()
                if v
            },
            "personas_del_grupo": len(people),
            "nominas_ordenadas": len(read),
            "sin_nomina_o_ilegible": len(people) - len(read),
            "cobertura": f"{len(read)} de {len(people)} personas del grupo",
            **(
                {
                    "aviso": f"{len(people) - len(read)} personas del grupo no tienen nómina legible en ese periodo: "
                    "el ranking no las incluye. Dilo al presentarlo."
                }
                if len(people) - len(read)
                else {}
            ),
            "orden": f"{p.orden} {p.importe}",
            "ranking": [
                {"puesto_en_el_ranking": i, "persona": e.name, "cargo": e.position, "importe": amount}
                for i, (e, amount) in enumerate(ordered, 1)
            ],
            "regla": RULE + " Importes individuales solo en pantalla, con permiso y auditoría.",
        }
        rows = [[i, e.name, e.position, format_eur(amount)] for i, (e, amount) in enumerate(ordered, 1)]
        return ToolResult(
            ToolStatus.OK if ordered else ToolStatus.NOT_FOUND,
            summary,
            table(f"Ranking de {p.importe} ({p.orden})", ["#", "Persona", "Puesto", "Importe"], rows),
        )

    return Tool(
        "ranking_salarial",
        f"Quién cobra más o menos dentro de un grupo (departamento o puesto), ordenado sobre TODAS las nóminas del "
        f"grupo: «los 3 que más cobraron en agosto en Cocina». Máximo 10 y grupos de {MIN_GROUP}+ personas; solo en "
        f"pantalla, con permiso y auditoría. Nunca ordenes salarios con una muestra parcial: usa esta herramienta.",
        RankingParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=120,
    )


def estadisticas_salariales(deps: Deps) -> Tool:
    async def handler(p: SalarialesParams, ctx: ToolContext) -> ToolResult:
        if problem := content_unavailable(deps):
            return problem
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
            people = [
                e
                for e in (await db.scalars(stmt)).all()
                if not p.puesto or normalize_key(p.puesto) in normalize_key(e.position)
            ]
            keys = {e.person_key for e in people}
            slips = (
                await db.scalars(
                    select(Payslip)
                    .where(
                        Payslip.person_key.in_(keys),
                        Payslip.special.is_(False),
                        *([Payslip.period == p.periodo] if p.periodo else []),
                    )
                    .order_by(Payslip.period.desc())
                )
            ).all()
        latest: dict[str, Payslip] = {}
        for s in slips:  # la más reciente de cada persona (o la del periodo pedido)
            if s.person_key and s.person_key not in latest:
                latest[s.person_key] = s
        if not people:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": "No hay personas con esos criterios."})
        sample = [e for e in people if e.person_key in latest][:MAX_PEOPLE]
        gate = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(*(_amounts(deps, latest[e.person_key or ""].sp_id, gate) for e in sample))
        read = [(e, r) for e, r in zip(sample, results, strict=True) if r]
        by_raw = {"puesto": lambda e: e.position, "departamento": lambda e: e.department}.get(p.agrupar_por)
        groups: dict[str, list[tuple[Employee, dict[str, float]]]] = {}
        group_display: dict[str, str] = {}  # clave normalizada → nombre canónico de visualización
        for e, r in read:
            raw = (by_raw(e) if by_raw else "Total") or "Sin dato"
            key = normalize_key(raw) if by_raw else "total"
            group_display.setdefault(key, raw)
            groups.setdefault(key, []).append((e, r))
        totals: dict[str, int] = {}
        for e in people:
            raw = (by_raw(e) if by_raw else "Total") or "Sin dato"
            key = normalize_key(raw) if by_raw else "total"
            totals[key] = totals.get(key, 0) + 1
        summary: dict[str, Any] = {
            "poblacion": population_label(p.incluir_inactivos),
            "criterios": {
                k: v
                for k, v in {
                    "puesto": p.puesto,
                    "departamento": p.departamento,
                    "periodo": p.periodo or "última nómina ordinaria",
                }.items()
                if v
            },
            "personas_del_grupo": len(people),
            "grupos": {
                group_display.get(g, g): _group_summary([r for _, r in m], totals.get(g, len(m)))
                for g, m in sorted(groups.items())
            },
            "regla": RULE,
        }
        rows = []
        for name, info in summary["grupos"].items():
            liquid = info.get("liquido", {})
            rows.append(
                [
                    name,
                    info["personas"],
                    liquid.get("media"),
                    liquid.get("mediana"),
                    liquid.get("suma"),
                    liquid.get("percentil_25"),
                    liquid.get("percentil_75"),
                    liquid.get("minimo"),
                    liquid.get("maximo"),
                ]
            )
        return ToolResult(
            ToolStatus.OK if read else ToolStatus.NOT_FOUND,
            summary,
            table(
                "Líquido mensual (agregado)",
                ["Grupo", "Personas", "Media", "Mediana", "Total", "P25", "P75", "Mínimo", "Máximo"],
                rows,
            ),
        )

    return Tool(
        "estadisticas_salariales",
        f"Estadísticas salariales de un grupo de la plantilla activa (suma, media, mediana, mínimo, máximo, "
        f"percentiles 25 y 75) de líquido, devengado y coste total empresa (devengado + SS patronal), para UN "
        f"único mes: por puesto, departamento o totales. "
        f"Responde «¿cuánto pagó la empresa en nóminas en agosto?», «¿cuál es el coste medio por empleado?», "
        f"«¿cuál es el percentil 25 en Cocina?» y «salario medio por departamento». "
        f"Para comparaciones interanuales (p. ej. «¿ha subido el salario medio de Pisos este año?»), "
        f"llámalo dos veces con distintos periodos y compara los resultados. "
        f"Para trimestres, años, varios meses o evolución temporal usa analisis_economico_nominas en su lugar "
        f"(resuelve el periodo y descarga todos los meses en paralelo). "
        f"Solo agregados: nunca el importe de una persona ni grupos de menos de {MIN_GROUP}. "
        f"No digas los importes en voz alta.",
        SalarialesParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=120,
    )
