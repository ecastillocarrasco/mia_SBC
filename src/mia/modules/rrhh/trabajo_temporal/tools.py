"""Trabajo temporal: empresas, trabajadores cedidos y boletines de horas."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import TtCommunication, TtCompany, TtRate, TtTimesheet, TtWorker
from mia.modules.rrhh.common import MAX_ROWS_FOR_MODEL, Deps, Periodo, fmt_date, table
from mia.modules.rrhh.content import MAX_BYTES, content_unavailable, document_text
from mia.text import normalize_key

KEYWORDS = (
    "ett",
    "trabajo temporal",
    "boletin",
    "boletín",
    "boletines",
    "empresa de trabajo temporal",
    "tarifa tt",
    "trabajador cedido",
    "trabajadores cedidos",
    "variacion de coste tt",
    "estimar coste tt",
    "trabajador temporal",
    "trabajadores temporales",
)
"""Ver `empleados.tools.KEYWORDS` para el criterio."""


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
        by_department: dict[str, dict[str, float]] = defaultdict(lambda: {"boletines": 0, "horas": 0.0, "importe": 0.0})
        by_company: dict[str, dict[str, float]] = defaultdict(lambda: {"boletines": 0, "horas": 0.0, "importe": 0.0})
        for r in rows:
            for key in (f"empresa: {r.company}", f"departamento: {r.department}"):
                totals[key]["boletines"] += 1
                totals[key]["horas"] += r.hours_total or 0.0
                totals[key]["importe"] += r.amount or 0.0
            for bucket, bucket_key in ((by_department, r.department), (by_company, r.company)):
                bucket[bucket_key]["boletines"] += 1
                bucket[bucket_key]["horas"] += r.hours_total or 0.0
                bucket[bucket_key]["importe"] += r.amount or 0.0
        importe_total = round(sum(r.amount or 0 for r in rows), 2)
        summary: dict[str, Any] = {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "boletines": len(rows),
            "horas_totales": round(sum(r.hours_total or 0 for r in rows), 2),
            "horas_nocturnas": round(sum(r.hours_night or 0 for r in rows), 2),
            "importe_total": importe_total,
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

        # Desglose por departamento y por empresa ETT con totales y porcentajes, además del listado
        # crudo de boletines: antes solo se exportaba la tabla fila a fila (762 registros en una
        # petición real), sin ningún total agregado ni gráfico -- "gastos... detalla totales y
        # porcentajes por departamento... y las cantidades abonadas a cada empresa" no tenía dónde
        # aparecer en pantalla ni en el PDF/Excel (incidencia real 2026-10-28).
        def _breakdown_table(title: str, label: str, buckets: dict[str, dict[str, float]]) -> dict[str, Any]:
            ordered = sorted(buckets.items(), key=lambda kv: -kv[1]["importe"])
            rows_out = [
                [
                    name,
                    int(v["boletines"]),
                    round(v["horas"], 2),
                    round(v["importe"], 2),
                    f"{round(v['importe'] / importe_total * 100, 1)}%" if importe_total else "—",
                ]
                for name, v in ordered
            ]
            return table(title, [label, "Boletines", "Horas", "Importe", "Peso %"], rows_out)

        dept_breakdown = _breakdown_table("Gasto de trabajo temporal por departamento", "Departamento", by_department)
        company_breakdown = _breakdown_table("Gasto abonado por empresa ETT", "Empresa", by_company)
        charts = [
            {
                "type": "donut",
                "title": "Gasto de trabajo temporal por departamento",
                "labels": [name for name, _ in sorted(by_department.items(), key=lambda kv: -kv[1]["importe"])],
                "series": [{
                    "name": "Importe",
                    "values": [round(v["importe"], 2) for _, v in sorted(by_department.items(), key=lambda kv: -kv[1]["importe"])],
                }],
            },
            {
                "type": "donut",
                "title": "Gasto abonado por empresa ETT",
                "labels": [name for name, _ in sorted(by_company.items(), key=lambda kv: -kv[1]["importe"])],
                "series": [{
                    "name": "Importe",
                    "values": [round(v["importe"], 2) for _, v in sorted(by_company.items(), key=lambda kv: -kv[1]["importe"])],
                }],
            },
        ] if by_department and by_company else []

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
                stats=dept_breakdown,
                tables=[company_breakdown],
                charts=charts,
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


# ------------------------------------------------------------------ tarifas ETT
class TarifasParams(BaseModel):
    empresa: str | None = Field(default=None, description="Filtrar por nombre de empresa ETT")


def tarifas_tt(deps: Deps) -> Tool:
    async def handler(p: TarifasParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(TtRate).order_by(TtRate.company)
            if p.empresa:
                key = normalize_key(p.empresa)
                stmt = stmt.where(TtRate.company_key.like(f"%{key}%"))
            rates = list((await db.scalars(stmt)).all())

        if not rates:
            return ToolResult(ToolStatus.NOT_FOUND, {"empresa": p.empresa, "nota": "Sin tarifas registradas."})

        def _fmt_time(t: Any) -> str:
            return str(t)[:5] if t else "—"

        rows = [
            [
                r.company or "—",
                f"{r.price_normal:.2f} €/h" if r.price_normal is not None else "—",
                f"{r.price_night:.2f} €/h" if r.price_night is not None else "—",
                f"{r.price_diet:.2f} €" if r.price_diet is not None else "—",
                f"{r.short_contract_surcharge:.2f} €" if r.short_contract_surcharge is not None else "—",
                f"{_fmt_time(r.normal_start)}–{_fmt_time(r.normal_end)}",
                f"{_fmt_time(r.night_start)}–{_fmt_time(r.night_end)}",
            ]
            for r in rates
        ]
        summary = {
            "empresas": len(rates),
            "tarifas": [
                {
                    "empresa": r.company,
                    "precio_normal": r.price_normal,
                    "precio_nocturno": r.price_night,
                    "dieta": r.price_diet,
                    "plus_contrato_corto": r.short_contract_surcharge,
                    "horario_diurno": f"{_fmt_time(r.normal_start)}-{_fmt_time(r.normal_end)}",
                    "horario_nocturno": f"{_fmt_time(r.night_start)}-{_fmt_time(r.night_end)}",
                }
                for r in rates
            ],
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                "Tarifas ETT",
                ["Empresa", "€/h Normal", "€/h Nocturno", "Dieta", "Plus corto", "Horario diurno", "Horario nocturno"],
                rows,
            ),
        )

    return Tool(
        "tarifas_tt",
        "Consulta las tarifas contratadas con cada ETT (empresa de trabajo temporal): precio/hora normal y nocturno, "
        "dieta y plus de contrato corto, con sus franjas horarias. Útil para estimar costes o resolver dudas de facturación.",
        TarifasParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


# ------------------------------------------------------------------ contactos ETT
class ContactosEttParams(BaseModel):
    empresa: str | None = Field(default=None, description="Nombre o parte del nombre de la ETT")


def contactos_ett(deps: Deps) -> Tool:
    async def handler(p: ContactosEttParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(TtCompany).order_by(TtCompany.name)
            if p.empresa:
                key = normalize_key(p.empresa)
                stmt = stmt.where(TtCompany.name.like(f"%{p.empresa}%"))
            companies = list((await db.scalars(stmt)).all())

        if not companies:
            return ToolResult(ToolStatus.NOT_FOUND, {"empresa": p.empresa, "nota": "Sin empresas ETT registradas."})

        rows = [[c.name, c.cif or "—", c.email or "—", c.phone or "—"] for c in companies]
        return ToolResult(
            ToolStatus.OK,
            {"empresas": [{"nombre": c.name, "cif": c.cif, "email": c.email, "telefono": c.phone} for c in companies]},
            table("Contactos ETT", ["Empresa", "CIF", "Email", "Teléfono"], rows),
        )

    return Tool(
        "contactos_ett",
        "Datos de contacto de las empresas de trabajo temporal (ETT): nombre, CIF, email y teléfono. "
        "Útil para resolver quién es el interlocutor de cada ETT.",
        ContactosEttParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


# ------------------------------------------------------------------ ETT activos hoy
class EttHoyParams(BaseModel):
    departamento: str | None = Field(default=None, description="Filtrar por departamento")
    empresa: str | None = Field(default=None, description="Filtrar por empresa ETT")


def ett_hoy(deps: Deps) -> Tool:
    async def handler(p: EttHoyParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        async with deps.db.session() as db:
            stmt = select(TtTimesheet).where(TtTimesheet.day == today)
            if p.departamento:
                key = normalize_key(p.departamento)
                stmt = stmt.where(TtTimesheet.department_key.like(f"%{key}%"))
            if p.empresa:
                stmt = stmt.where(TtTimesheet.company.like(f"%{p.empresa}%"))
            sheets = list((await db.scalars(stmt.order_by(TtTimesheet.department, TtTimesheet.worker_name))).all())

        if not sheets:
            return ToolResult(ToolStatus.OK, {"fecha": str(today), "total": 0, "nota": "Sin boletines ETT para hoy."})

        by_dept: Counter[str] = Counter()
        by_company: Counter[str] = Counter()
        total_h = 0.0
        for s in sheets:
            by_dept[s.department or "Sin dato"] += 1
            by_company[s.company or "Sin dato"] += 1
            total_h += s.hours_total or 0

        rows = [
            [
                s.worker_name or "—",
                s.company or "—",
                s.department or "—",
                s.start_time or "—",
                s.end_time or "—",
                s.hours_total or 0,
            ]
            for s in sheets
        ]
        return ToolResult(
            ToolStatus.OK,
            {
                "fecha": str(today),
                "total_trabajadores_ett": len(sheets),
                "horas_totales": round(total_h, 1),
                "por_departamento": dict(by_dept.most_common()),
                "por_empresa": dict(by_company.most_common()),
            },
            table(
                f"Trabajadores ETT hoy ({fmt_date(today)})",
                ["Trabajador", "ETT", "Departamento", "Inicio", "Fin", "Horas"],
                rows,
            ),
        )

    return Tool(
        "ett_hoy",
        "Trabajadores de ETT con boletín para hoy: nombre, empresa, departamento y horario. "
        "Muestra el total y el desglose por departamento y empresa.",
        EttHoyParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
    )


# ------------------------------------------------------------------ boletines faltantes ETT
class BoletinesFaltantesParams(Periodo):
    empresa: str | None = None
    departamento: str | None = None


def boletines_faltantes(deps: Deps) -> Tool:
    async def handler(p: BoletinesFaltantesParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo, hi = p.resolve(today.replace(day=1), default_days=0)
        if not p.desde and not p.hasta:
            hi = today
        async with deps.db.session() as db:
            workers = list(
                (await db.scalars(select(TtWorker).where(TtWorker.visible.is_(True)).order_by(TtWorker.name))).all()
            )
            worker_ids_with_boletin: set[int] = set(
                (
                    await db.scalars(
                        select(TtTimesheet.worker_id)
                        .where(TtTimesheet.day.between(lo, hi), TtTimesheet.worker_id.isnot(None))
                        .distinct()
                    )
                ).all()
            )
            fresh = await deps.freshness(db, "tt_boletines", "tt_trabajadores")
        if p.empresa:
            workers = [w for w in workers if normalize_key(p.empresa) in normalize_key(w.company or "")]
        if p.departamento:
            workers = [w for w in workers if normalize_key(p.departamento) in normalize_key(w.department or "")]
        missing = [w for w in workers if w.sp_id not in worker_ids_with_boletin]
        summary: dict[str, Any] = {
            "desde": lo.isoformat(),
            "hasta": hi.isoformat(),
            "trabajadores_activos": len(workers),
            "sin_boletin": len(missing),
            "empresa": p.empresa or "todas",
            "departamento": p.departamento or "todos",
            **fresh,
        }
        if len(missing) <= MAX_ROWS_FOR_MODEL:
            summary["trabajadores_sin_boletin"] = [
                {"nombre": w.name, "empresa": w.company, "departamento": w.department} for w in missing
            ]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"ETT sin boletín ({lo.isoformat()} – {hi.isoformat()})",
                ["Nombre", "Empresa", "Departamento"],
                [[w.name, w.company, w.department] for w in missing],
            ),
        )

    return Tool(
        "boletines_faltantes_tt",
        "Trabajadores de ETT visibles que no tienen ningún boletín de horas en el periodo indicado "
        "(por defecto, el mes en curso). Responde «¿hay trabajadores ETT sin boletín este mes?».",
        BoletinesFaltantesParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
        audit_resource="trabajo_temporal",
    )


# ------------------------------------------------------------------ variación de coste ETT
class VariacionCosteTtParams(BaseModel):
    empresa: str | None = None
    departamento: str | None = None
    desde_ref: date | None = Field(
        default=None,
        description="Inicio del periodo de referencia (por defecto: inicio del mes anterior)",
    )
    hasta_ref: date | None = Field(
        default=None,
        description="Fin del periodo de referencia (por defecto: fin del mes anterior)",
    )
    desde_actual: date | None = Field(
        default=None,
        description="Inicio del periodo actual (por defecto: inicio del mes en curso)",
    )
    hasta_actual: date | None = Field(
        default=None,
        description="Fin del periodo actual (por defecto: hoy)",
    )


def variacion_coste(deps: Deps) -> Tool:
    async def handler(p: VariacionCosteTtParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        lo_actual = p.desde_actual or today.replace(day=1)
        hi_actual = p.hasta_actual or today
        if not p.desde_ref and not p.hasta_ref:
            last_of_prev = today.replace(day=1) - timedelta(days=1)
            lo_ref: date = last_of_prev.replace(day=1)
            hi_ref: date = last_of_prev
        else:
            prev_last = today.replace(day=1) - timedelta(days=1)
            lo_ref = p.desde_ref or prev_last.replace(day=1)
            hi_ref = p.hasta_ref or prev_last

        async with deps.db.session() as db:

            async def _fetch(lo: date, hi: date) -> list[TtTimesheet]:
                stmt = select(TtTimesheet).where(TtTimesheet.day.between(lo, hi))
                if p.departamento:
                    stmt = stmt.where(TtTimesheet.department_key.like(f"%{normalize_key(p.departamento)}%"))
                return list((await db.scalars(stmt)).all())

            rows_ref = await _fetch(lo_ref, hi_ref)
            rows_actual = await _fetch(lo_actual, hi_actual)
            fresh = await deps.freshness(db, "tt_boletines")

        if p.empresa:
            key = normalize_key(p.empresa)
            rows_ref = [r for r in rows_ref if key in normalize_key(r.company or "")]
            rows_actual = [r for r in rows_actual if key in normalize_key(r.company or "")]

        importe_ref = round(sum(r.amount or 0 for r in rows_ref), 2)
        importe_actual = round(sum(r.amount or 0 for r in rows_actual), 2)
        horas_ref = round(sum(r.hours_total or 0 for r in rows_ref), 2)
        horas_actual = round(sum(r.hours_total or 0 for r in rows_actual), 2)

        def _pct(before: float, after: float) -> str:
            if before == 0:
                return "N/A"
            return f"{(after - before) / before * 100:+.1f}%"

        delta_importe = round(importe_actual - importe_ref, 2)
        delta_horas = round(horas_actual - horas_ref, 2)
        delta_boletines = len(rows_actual) - len(rows_ref)

        return ToolResult(
            ToolStatus.OK,
            {
                "empresa": p.empresa or "todas",
                "departamento": p.departamento or "todos",
                "referencia": {
                    "desde": lo_ref.isoformat(),
                    "hasta": hi_ref.isoformat(),
                    "boletines": len(rows_ref),
                    "horas": horas_ref,
                    "importe": importe_ref,
                },
                "actual": {
                    "desde": lo_actual.isoformat(),
                    "hasta": hi_actual.isoformat(),
                    "boletines": len(rows_actual),
                    "horas": horas_actual,
                    "importe": importe_actual,
                },
                "variacion": {
                    "importe": delta_importe,
                    "importe_pct": _pct(importe_ref, importe_actual),
                    "horas": delta_horas,
                    "horas_pct": _pct(horas_ref, horas_actual),
                    "boletines": delta_boletines,
                },
                **fresh,
            },
            table(
                "Variación coste ETT",
                ["Concepto", "Referencia", "Actual", "Variación"],
                [
                    [
                        "Importe (€)",
                        importe_ref,
                        importe_actual,
                        f"{_pct(importe_ref, importe_actual)} ({delta_importe:+.2f} €)",
                    ],
                    ["Horas", horas_ref, horas_actual, f"{_pct(horas_ref, horas_actual)} ({delta_horas:+.2f} h)"],
                    ["Boletines", len(rows_ref), len(rows_actual), f"{delta_boletines:+d}"],
                ],
            ),
        )

    return Tool(
        "variacion_coste_tt",
        "Compara coste, horas y boletines de ETT entre dos periodos. Por defecto compara el mes en curso con el "
        "mes anterior. Responde «¿qué variación de coste de ETT hay respecto al mes pasado?».",
        VariacionCosteTtParams,
        handler,
        permission=Permission.TRABAJO_TEMPORAL_LEER,
        audit_resource="trabajo_temporal",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (
        trabajadores,
        boletines,
        boletines_faltantes,
        variacion_coste,
        estimar_coste,
        anomalias,
        comunicaciones,
        tarifas_tt,
        contactos_ett,
        ett_hoy,
    ):
        registry.register(factory(deps))
