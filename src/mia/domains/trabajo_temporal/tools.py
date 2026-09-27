"""Trabajo temporal: empresas, trabajadores cedidos y boletines de horas."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import TtCompany, TtTimesheet, TtWorker
from mia.domains.common import MAX_ROWS_FOR_MODEL, Deps, Periodo, fmt_date, table
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
                r
                for r in rows
                if all(t in normalize_key(r.worker_name) for t in normalize_key(p.trabajador).split())
            ]
        if p.estado:
            rows = [r for r in rows if normalize_key(p.estado) in normalize_key(r.status)]
        totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {"boletines": 0, "horas": 0.0, "importe": 0.0}
        )
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


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (trabajadores, boletines):
        registry.register(factory(deps))
