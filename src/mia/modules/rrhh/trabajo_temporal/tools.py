"""Trabajo temporal: empresas, trabajadores cedidos y boletines de horas."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import TtCommunication, TtCompany, TtRate, TtTimesheet, TtWorker
from mia.modules.rrhh.common import MAX_ROWS_FOR_MODEL, Deps, Periodo, fmt_date, table
from mia.modules.rrhh.content import MAX_BYTES, content_unavailable, document_text
from mia.text import normalize_key


class TrabajadoresParams(BaseModel):
    empresa: str | None = None
    departamento: str | None = None
    nombre: str | None = None
    incluir_no_visibles: bool = False


def trabajadores(deps: Deps) -> Tool:
    async def handler(p: TrabajadoresParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(TtWorker)
            if not p.incluir_no_visibles:
                stmt = stmt.where(TtWorker.visible.is_(True))
            if p.nombre:
                for token in normalize_key(p.nombre).split():
                    stmt = stmt.where(TtWorker.name_key.like(f"%{token}%"))
            workers = list((await db.scalars(stmt.order_by(TtWorker.name))).all())
            companies = list((await db.scalars(select(TtCompany).order_by(TtCompany.name))).all())
            fresh = await deps.freshness(db, "tt_trabajadores", "tt_empresas")
        if p.empresa:
            workers = [w for w in workers if normalize_key(p.empresa) in normalize_key(w.company)]
        if p.departamento:
            workers = [w for w in workers if normalize_key(p.departamento) in normalize_key(w.department)]
        summary: dict[str, Any] = {
            "total": len(workers),
            "empresas": [c.name for c in companies],
            **fresh,
        }
        if len(workers) <= MAX_ROWS_FOR_MODEL:
            summary["trabajadores"] = [
                {"nombre": w.name, "empresa": w.company, "departamento": w.department} for w in workers
            ]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                "Trabajo temporal",
                ["Nombre", "Empresa", "Departamento"],
                [[w.name, w.company, w.department] for w in workers],
            ),
        )

    return Tool(
        "trabajadores_tt",
        "Trabajadores de ETT (por empresa, departamento o nombre) y lista de empresas.",
        TrabajadoresParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


class BoletinesParams(Periodo):
    empresa: str | None = None
    departamento: str | None = None
    trabajador: str | None = None
    estado: str | None = None


def boletines(deps: Deps) -> Tool:
    async def handler(p: BoletinesParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo, hi = p.resolve(today.replace(day=1), default_days=0)
        if not p.hasta and not p.desde:
            hi = today
        async with deps.db.session() as db:
            stmt = select(TtTimesheet).where(TtTimesheet.day.between(lo, hi))
            if p.departamento:
                stmt = stmt.where(TtTimesheet.department_key.like(f"%{normalize_key(p.departamento)}%"))
            rows = list((await db.scalars(stmt.order_by(TtTimesheet.day))).all())
            fresh = await deps.freshness(db, "tt_boletines")
        if p.empresa:
            rows = [r for r in rows if normalize_key(p.empresa) in normalize_key(r.company)]
        if p.trabajador:
            rows = [
                r for r in rows if all(t in normalize_key(r.worker_name) for t in normalize_key(p.trabajador).split())
            ]
        if p.estado:
            rows = [r for r in rows if normalize_key(p.estado) in normalize_key(r.status)]
        totals: dict[str, dict[str, float]] = defaultdict(lambda: {"boletines": 0, "horas": 0.0, "importe": 0.0})
        for r in rows:
            for key in (f"empresa: {r.company}", f"departamento: {r.department}"):
                totals[key]["boletines"] += 1
                totals[key]["horas"] += r.hours_total or 0.0
                totals[key]["importe"] += r.amount or 0.0
        summary: dict[str, Any] = {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "boletines": len(rows),
            "horas_totales": round(sum(r.hours_total or 0 for r in rows), 2),
            "horas_nocturnas": round(sum(r.hours_night or 0 for r in rows), 2),
            "importe_total": round(sum(r.amount or 0 for r in rows), 2),
            "desglose": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in totals.items()},
            **fresh,
        }
        if len(rows) <= MAX_ROWS_FOR_MODEL:
            summary["detalle"] = [
                {
                    "fecha": fmt_date(r.day),
                    "trabajador": r.worker_name,
                    "empresa": r.company,
                    "horas": r.hours_total,
                    "estado": r.status,
                }
                for r in rows
            ]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                "Boletines de trabajo temporal",
                ["Fecha", "Trabajador", "Empresa", "Departamento", "Horas", "Importe", "Estado"],
                [
                    [
                        fmt_date(r.day),
                        r.worker_name,
                        r.company,
                        r.department,
                        r.hours_total,
                        r.amount,
                        r.status,
                    ]
                    for r in rows
                ],
            ),
        )

    return Tool(
        "boletines_tt",
        "Boletines de horas de trabajo temporal en un periodo (por defecto, el mes en curso): horas, "
        "importe y desglose por empresa y departamento.",
        BoletinesParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
        audit_resource="trabajo_temporal",
    )


# ------------------------------------------------------------------ fase 4b
class EstimarParams(BaseModel):
    empresa: str = Field(description="Empresa de trabajo temporal")
    horas_normales: float = Field(default=0, ge=0)
    horas_nocturnas: float = Field(default=0, ge=0)
    dietas: float = Field(default=0, ge=0)
    aplicar_recargo_corta_duracion: bool = False


def estimar_coste(deps: Deps) -> Tool:
    async def handler(p: EstimarParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            rates = list((await db.scalars(select(TtRate))).all())
        rate = next((r for r in rates if normalize_key(p.empresa) in r.company_key), None)
        if rate is None:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                {
                    "mensaje": "No hay tarifas para esa empresa.",
                    "empresas_con_tarifa": [r.company for r in rates],
                },
            )
        base = (
            p.horas_normales * (rate.price_normal or 0)
            + p.horas_nocturnas * (rate.price_night or 0)
            + p.dietas * (rate.price_diet or 0)
        )
        surcharge = (rate.short_contract_surcharge or 0) if p.aplicar_recargo_corta_duracion else 0.0
        return ToolResult(
            ToolStatus.OK,
            {
                "empresa": rate.company,
                "tarifas": {
                    "hora_normal": rate.price_normal,
                    "hora_nocturna": rate.price_night,
                    "dieta": rate.price_diet,
                },
                "coste_base": round(base, 2),
                "recargo_pct": surcharge,
                "coste_estimado": round(base * (1 + surcharge / 100), 2),
                "nota": "Estimación con las tarifas actuales de SettingsTT; no sustituye el importe "
                "histórico de los boletines.",
            },
        )

    return Tool(
        "estimar_coste_tt",
        "Estima el coste de horas de ETT con las tarifas actuales de la empresa.",
        EstimarParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


class AnomaliasParams(Periodo):
    empresa: str | None = None


def anomalias(deps: Deps) -> Tool:
    async def handler(p: AnomaliasParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo, hi = p.resolve(today.replace(day=1), default_days=0)
        if not p.desde and not p.hasta:
            hi = today
        async with deps.db.session() as db:
            rows = list((await db.scalars(select(TtTimesheet).where(TtTimesheet.day.between(lo, hi)))).all())
            rates = {r.company_key: r for r in (await db.scalars(select(TtRate))).all()}
        if p.empresa:
            rows = [r for r in rows if normalize_key(p.empresa) in normalize_key(r.company)]
        issues: list[dict[str, Any]] = []
        seen: dict[tuple[str | None, Any], int] = defaultdict(int)
        for r in rows:
            seen[(normalize_key(r.worker_name), r.day)] += 1
        for r in rows:
            problems = []
            if (r.hours_total or 0) > 12:
                problems.append("más de 12 horas en un día")
            if (r.hours_total or 0) <= 0:
                problems.append("sin horas")
            if seen[(normalize_key(r.worker_name), r.day)] > 1:
                problems.append("más de un boletín de la misma persona el mismo día")
            rate = rates.get(normalize_key(r.company))
            if rate and r.amount and r.hours_total:
                expected = (r.hours_normal or 0) * (rate.price_normal or 0) + (r.hours_night or 0) * (
                    rate.price_night or 0
                )
                if expected and abs(r.amount - expected) / expected > 0.25:
                    problems.append("importe muy distinto a las tarifas actuales (orientativo)")
            if problems:
                issues.append(
                    {
                        "fecha": fmt_date(r.day),
                        "trabajador": r.worker_name,
                        "empresa": r.company,
                        "horas": r.hours_total,
                        "importe": r.amount,
                        "motivos": problems,
                    }
                )
        return ToolResult(
            ToolStatus.OK,
            {
                "desde": lo.isoformat(),
                "hasta": hi.isoformat(),
                "boletines_revisados": len(rows),
                "con_anomalias": len(issues),
                "anomalias": issues[:40],
            },
            table(
                "Anomalías en boletines TT",
                ["Fecha", "Trabajador", "Empresa", "Horas", "Importe", "Motivos"],
                [
                    [
                        i["fecha"],
                        i["trabajador"],
                        i["empresa"],
                        i["horas"],
                        i["importe"],
                        "; ".join(i["motivos"]),
                    ]
                    for i in issues
                ],
            ),
        )

    return Tool(
        "anomalias_tt",
        "Detecta boletines de ETT anómalos: exceso de horas, sin horas, duplicados e importes alejados de las tarifas.",
        AnomaliasParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


class ComunicacionesParams(BaseModel):
    buscar: str | None = Field(default=None, description="Texto a buscar en el nombre (p. ej. la empresa: RANDSTAD)")
    leer_ultimas: int = Field(
        default=0, ge=0, le=8, description="Leer el contenido de las N más recientes para resumirlas"
    )


def comunicaciones(deps: Deps) -> Tool:
    async def handler(p: ComunicacionesParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            rows = list((await db.scalars(select(TtCommunication).order_by(TtCommunication.created_at.desc()))).all())
        if p.buscar:
            rows = [r for r in rows if normalize_key(p.buscar) in normalize_key(f"{r.title} {r.file_name}")]
        items: list[dict[str, Any]] = [
            {"documento": r.file_name or r.title, "fecha": fmt_date(r.created_at.date()) if r.created_at else None}
            for r in rows
        ]
        contents: list[dict[str, Any]] = []
        if p.leer_ultimas and rows:
            if problem := content_unavailable(deps):
                return problem
            for r in rows[: p.leer_ultimas]:
                try:
                    raw = await deps.sharepoint.download_item_file("ComunicacionesBoletinesTT", r.sp_id, MAX_BYTES)
                    text = document_text(raw) or ""
                except Exception as exc:  # un documento ilegible no impide leer los demás
                    text = f"(no se ha podido leer: {type(exc).__name__})"
                contents.append({"documento": r.file_name or r.title, "texto": text[:1500]})
        summary: dict[str, Any] = {
            "total": len(items),
            "comunicaciones": items[:40],
            "nota": "Documentos de comunicación con ETT; no equivalen 1:1 a boletines.",
        }
        if contents:
            summary["contenido_de_las_ultimas"] = contents
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Comunicaciones ETT", ["Documento", "Fecha"], [list(i.values()) for i in items]),
        )

    return Tool(
        "comunicaciones_tt",
        "Comunicaciones con las ETT (filtrables por empresa con «buscar») y, con leer_ultimas, el contenido de "
        "las más recientes para resumirlas.",
        ComunicacionesParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (trabajadores, boletines, estimar_coste, anomalias, comunicaciones):
        registry.register(factory(deps))
