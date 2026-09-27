"""Nóminas: qué nóminas existen, de qué periodo y si se han leído.

NOM-002: el contenido de las nóminas (importes) no se lee ni se guarda. mIA
informa de existencia, periodo y lectura; para importes hay que abrir la nómina.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from pydantic import Field
from sqlalchemy import and_, or_, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, Payslip
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    CohortParams,
    Deps,
    PersonaParams,
    department_problem,
    focus_person,
    no_population,
    person_problem,
    population_state,
    previous_population,
    resolve_department,
    resolve_person,
    table,
)
from mia.domains.content import MAX_BYTES, content_unavailable, pdf_lines
from mia.domains.nominas.parser import parse_payslip

RULE = "Metadatos (existencia, periodo, lectura). Para importes: nomina_importes o evolucion_nominas (NOM-002)."


def _belongs(e: Employee) -> Any:
    """La carpeta (DNI seudonimizado) manda; UsuarioNomina solo se usa si la nómina no está en carpeta."""
    conditions = []
    if e.person_key:
        conditions.append(Payslip.person_key == e.person_key)
    if e.email:
        conditions.append(and_(Payslip.person_key.is_(None), Payslip.employee_email == e.email))
    return or_(*conditions) if conditions else Payslip.sp_id < 0


class NominasPersonaParams(PersonaParams):
    anio: int | None = Field(default=None, description="Año (por defecto, el actual)")
    solo_no_leidas: bool = False


def nominas_persona(deps: Deps) -> Tool:
    async def handler(p: NominasPersonaParams, ctx: ToolContext) -> ToolResult:
        year = p.anio or ctx.now.year
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            stmt = select(Payslip).where(_belongs(e), Payslip.year == year)
            if p.solo_no_leidas:
                stmt = stmt.where(Payslip.read.is_(False))
            rows = list((await db.scalars(stmt.order_by(Payslip.period, Payslip.sp_id))).all())
            fresh = await deps.freshness(db, "nominas")
        items = [
            {
                "periodo": r.period,
                "concepto": r.label,
                "paga_especial": r.special,
                "leida": r.read,
                "enlace": f"/api/documents/nomina/{r.sp_id}",
            }
            for r in rows
        ]
        months = {r.month for r in rows if r.month and not r.special}
        last_month = ctx.now.month - 1 if year == ctx.now.year else 12
        missing = [m for m in range(1, max(0, last_month) + 1) if m not in months]
        summary: dict[str, Any] = {
            "persona": e.name,
            "anio": year,
            "total": len(items),
            "nominas": items,
            "meses_sin_nomina_hasta_el_mes_pasado": missing,
            "no_leidas": sum(1 for r in rows if r.read is False),
            "regla": RULE,
            **fresh,
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Nóminas {year} · {e.name}",
                ["Periodo", "Concepto", "Especial", "Leída", "Enlace"],
                [
                    [i["periodo"], i["concepto"], "Sí" if i["paga_especial"] else "", i["leida"], i["enlace"]]
                    for i in items
                ],
            ),
            focus_person(e),
        )

    return Tool(
        "nominas_persona",
        "Nóminas de una persona en un año: periodos, pagas especiales, si están leídas y meses que faltan. "
        "No da importes.",
        NominasPersonaParams,
        handler,
        permission=Permission.NOMINAS_LEER,
        audit_resource="nominas",
    )


class NominasPeriodoParams(CohortParams):
    periodo: str = Field(description="Mes AAAA-MM, p. ej. 2026-08")
    departamento: str | None = None


def nominas_periodo(deps: Deps) -> Tool:
    async def handler(p: NominasPeriodoParams, ctx: ToolContext) -> ToolResult:
        try:
            year, month = (int(x) for x in p.periodo.split("-", 1))
            date(year, month, 1)
        except ValueError:
            return ToolResult(ToolStatus.INVALID_ARGUMENTS, "El periodo debe ser AAAA-MM")
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(Employee).where(Employee.active.is_(True))
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
            if p.sobre_resultado_anterior:
                if (previous := previous_population(ctx)) is None:
                    return no_population()
                stmt = stmt.where(Employee.sp_id.in_(previous["empleado_ids"]))
            employees = list((await db.scalars(stmt)).all())
            slips = list((await db.scalars(select(Payslip).where(Payslip.period == p.periodo))).all())
            fresh = await deps.freshness(db, "nominas", "empleados")
        by_folder = {s.person_key for s in slips if s.person_key}
        by_mail = {s.employee_email for s in slips if not s.person_key and s.employee_email}
        missing = [e for e in employees if e.person_key not in by_folder and e.email not in by_mail]
        unread = [s for s in slips if s.read is False]
        summary: dict[str, Any] = {
            "periodo": p.periodo,
            "departamento": dept.name or "toda la plantilla activa",
            "plantilla_activa": len(employees),
            "con_nomina": len(employees) - len(missing),
            "sin_nomina": len(missing),
            "nominas_no_leidas": len(unread),
            "regla": RULE,
            **fresh,
        }
        if len(missing) <= MAX_ROWS_FOR_MODEL:
            summary["personas_sin_nomina"] = [e.name for e in missing]
        state = population_state(f"sin nómina en {p.periodo}", missing)
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Sin nómina en {p.periodo}",
                ["Persona", "Departamento"],
                [[e.name, e.department] for e in missing],
            ),
            state,
        )

    return Tool(
        "nominas_periodo",
        "Cobertura de nóminas de un mes: quién de la plantilla activa no la tiene y cuántas no se han leído.",
        NominasPeriodoParams,
        handler,
        permission=Permission.NOMINAS_LEER,
        audit_resource="nominas",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (nominas_persona, nominas_periodo):
        registry.register(factory(deps))
    register_amounts(registry, deps)


# ------------------------------------------------------------------ importes (NOM-003)
AMOUNTS_RULE = "NOM-003: importes leídos en el momento del PDF de la nómina; no se guardan. No los digas en voz alta."


async def _read_amounts(deps: Deps, slip: Payslip) -> dict[str, Any]:
    try:
        content = await deps.sharepoint.download_item_file("Nominas", slip.sp_id, MAX_BYTES)
        parsed = parse_payslip(pdf_lines(content))
    except Exception as exc:  # PDF ilegible o fuente caída: se informa, no se inventa
        return {
            "periodo": slip.period,
            "concepto": slip.label,
            "error": f"No se ha podido leer: {type(exc).__name__}",
        }
    return {"periodo": slip.period, "concepto": slip.label, "paga_especial": slip.special, **parsed}


class ImportesParams(PersonaParams):
    periodo: str | None = Field(default=None, description="AAAA-MM; por defecto, la última nómina ordinaria")
    incluir_pagas_especiales: bool = False


def nomina_importes(deps: Deps) -> Tool:
    async def handler(p: ImportesParams, ctx: ToolContext) -> ToolResult:
        if problem := content_unavailable(deps):
            return problem
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            stmt = select(Payslip).where(_belongs(e))
            if p.periodo:
                stmt = stmt.where(Payslip.period == p.periodo)
            if not p.incluir_pagas_especiales:
                stmt = stmt.where(Payslip.special.is_(False))
            slips = list((await db.scalars(stmt.order_by(Payslip.period.desc()).limit(3 if p.periodo else 1))).all())
        if not slips:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": f"No hay nómina de {e.name} para ese periodo."})
        results = [await _read_amounts(deps, s) for s in slips]
        return ToolResult(
            ToolStatus.OK,
            {"persona": e.name, "nominas": results, "regla": AMOUNTS_RULE},
            {"type": "payslip", "persona": e.name, "nominas": results},
            focus_person(e),
        )

    return Tool(
        "nomina_importes",
        "Importes de una nómina (devengado, deducciones, líquido, IRPF) leídos del PDF en el momento.",
        ImportesParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=45,
    )


class EvolucionParams(PersonaParams):
    anio: int | None = Field(default=None, description="Año (por defecto, el actual)")


def evolucion_nominas(deps: Deps) -> Tool:
    async def handler(p: EvolucionParams, ctx: ToolContext) -> ToolResult:
        if problem := content_unavailable(deps):
            return problem
        year = p.anio or ctx.now.year
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            slips = list(
                (
                    await db.scalars(select(Payslip).where(_belongs(e), Payslip.year == year).order_by(Payslip.period))
                ).all()
            )
        if not slips:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": f"No hay nóminas de {e.name} en {year}."})
        results = list(await asyncio.gather(*(_read_amounts(deps, s) for s in slips[:16])))
        rows = [
            [
                r["periodo"],
                r.get("concepto"),
                "Sí" if r.get("paga_especial") else "",
                *(
                    r.get("importes", {}).get(k)
                    for k in ("total_devengado", "total_deducciones", "liquido", "irpf_porcentaje")
                ),
            ]
            for r in results
        ]
        ordinary = [r for r in results if not r.get("paga_especial") and r.get("importes", {}).get("liquido")]
        summary = {
            "persona": e.name,
            "anio": year,
            "nominas": results,
            "liquido_total": round(
                sum(r["importes"]["liquido"] for r in results if r.get("importes", {}).get("liquido")), 2
            ),
            "liquido_medio_ordinario": (
                round(sum(r["importes"]["liquido"] for r in ordinary) / len(ordinary), 2) if ordinary else None
            ),
            "regla": AMOUNTS_RULE,
        }
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Nóminas {year} · {e.name}",
                ["Periodo", "Concepto", "Especial", "Devengado", "Deducciones", "Líquido", "IRPF %"],
                rows,
            ),
            focus_person(e),
        )

    return Tool(
        "evolucion_nominas",
        "Evolución de los importes de las nóminas de una persona en un año (y comparaciones entre meses).",
        EvolucionParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=90,
    )


def register_amounts(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (nomina_importes, evolucion_nominas):
        registry.register(factory(deps))
