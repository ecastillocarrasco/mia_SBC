"""Nóminas: qué nóminas existen, de qué periodo y si se han leído.

NOM-002: el contenido de las nóminas (importes) no se lee ni se guarda. mIA
informa de existencia, periodo y lectura; para importes hay que abrir la nómina.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, Payslip
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    Deps,
    PersonaParams,
    department_problem,
    focus_person,
    person_problem,
    resolve_department,
    resolve_person,
    table,
)

RULE = "NOM-002: no se leen importes; solo existencia, periodo y si la nómina se ha abierto."


def _belongs(e: Employee) -> Any:
    conditions = []
    if e.person_key:
        conditions.append(Payslip.person_key == e.person_key)
    if e.email:
        conditions.append(Payslip.employee_email == e.email)
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
            {"periodo": r.period, "concepto": r.label, "paga_especial": r.special, "leida": r.read}
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
                ["Periodo", "Concepto", "Especial", "Leída"],
                [
                    [i["periodo"], i["concepto"], "Sí" if i["paga_especial"] else "", i["leida"]]
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


class NominasPeriodoParams(BaseModel):
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
            employees = list((await db.scalars(stmt)).all())
            slips = list((await db.scalars(select(Payslip).where(Payslip.period == p.periodo))).all())
            fresh = await deps.freshness(db, "nominas", "empleados")
        by_key = {s.person_key for s in slips if s.person_key} | {
            s.employee_email for s in slips if s.employee_email
        }
        missing = [e for e in employees if not ({e.person_key, e.email} & by_key)]
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
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Sin nómina en {p.periodo}",
                ["Persona", "Departamento"],
                [[e.name, e.department] for e in missing],
            ),
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
