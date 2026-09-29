"""Cruce entre dominios sobre un mismo grupo de personas.

«De los que están de vacaciones, ¿qué puesto tienen y cuánto saldo les queda?» → se toma el grupo del
resultado anterior (o una lista de personas) y se añaden, por persona, los datos pedidos de cada dominio:
ficha (EmpleadosCorporativos), turno de hoy, saldo y próximas vacaciones, nóminas y documentos firmados.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, Payslip, ShiftDay, SignedDocument, Vacation, VacationBalance
from mia.domains.common import Deps, fmt_date, no_population, previous_population, table
from mia.domains.empleados.tools import age

Campo = Literal[
    "puesto",
    "departamento",
    "responsable",
    "activo",
    "edad",
    "email",
    "telefono",
    "turno_hoy",
    "saldo_vacaciones",
    "proximas_vacaciones",
    "ultima_nomina",
    "nominas_no_leidas",
    "documentos_firmados",
    "nacionalidad",
    "codigo_empleado",
    "cumpleanos",
]
LABELS: dict[str, str] = {
    "puesto": "Puesto",
    "departamento": "Departamento",
    "responsable": "Responsable",
    "activo": "Activo",
    "edad": "Edad",
    "email": "Email",
    "telefono": "Teléfono",
    "turno_hoy": "Hoy",
    "saldo_vacaciones": "Saldo vacaciones",
    "proximas_vacaciones": "Próximas vacaciones",
    "ultima_nomina": "Última nómina",
    "nominas_no_leidas": "Nóminas sin leer",
    "documentos_firmados": "Docs. firmados",
    "nacionalidad": "Nacionalidad",
    "codigo_empleado": "Código",
    "cumpleanos": "Cumpleaños",
}
MAX_PEOPLE = 300


class CruceParams(BaseModel):
    campos: list[Campo] = Field(min_length=1, description="Datos que añadir a cada persona")
    empleado_ids: list[int] | None = Field(default=None, description="Personas concretas (ids del foco o búsqueda)")
    resultado: str | None = Field(
        default=None, description="Parte de la etiqueta de un resultado anterior que no es el último"
    )


async def _employees(deps: Deps, p: CruceParams, ctx: ToolContext) -> list[Employee] | None:
    ids = p.empleado_ids
    if not ids:
        population = previous_population(ctx, p.resultado)
        if not population:
            return None
        ids = population.get("empleado_ids") or []
    async with deps.db.session() as db:
        return list((await db.scalars(select(Employee).where(Employee.sp_id.in_(ids[:MAX_PEOPLE])))).all())


async def _extra(deps: Deps, people: list[Employee], fields: set[str], today: date) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {e.sp_id: {} for e in people}
    by_key = {e.person_key: e.sp_id for e in people if e.person_key}
    by_mail = {e.email.lower(): e.sp_id for e in people if e.email}
    async with deps.db.session() as db:
        if "turno_hoy" in fields and by_key:
            for s in (
                await db.scalars(select(ShiftDay).where(ShiftDay.day == today, ShiftDay.person_key.in_(by_key)))
            ).all():
                out[by_key[s.person_key or ""]]["turno_hoy"] = f"{s.kind} · {s.raw_value}" if s.raw_value else s.kind
        if "saldo_vacaciones" in fields and by_mail:
            balances = select(VacationBalance).where(
                VacationBalance.year == today.year, func.lower(VacationBalance.employee_email).in_(by_mail)
            )
            for b in (await db.scalars(balances)).all():
                out[by_mail[(b.employee_email or "").lower()]]["saldo_vacaciones"] = (
                    f"{b.current_balance} de {b.total_balance}"
                )
        if "proximas_vacaciones" in fields and by_mail:
            stmt = (
                select(Vacation)
                .where(Vacation.end_date >= today, func.lower(Vacation.employee_email).in_(by_mail))
                .order_by(Vacation.start_date)
            )
            for v in (await db.scalars(stmt)).all():
                if (v.status or "").lower().startswith("acept"):
                    out[by_mail[(v.employee_email or "").lower()]].setdefault(
                        "proximas_vacaciones", f"{fmt_date(v.start_date)}–{fmt_date(v.end_date)}"
                    )
        if {"ultima_nomina", "nominas_no_leidas"} & fields and by_key:
            for key, last, unread in (
                await db.execute(
                    select(
                        Payslip.person_key,
                        func.max(Payslip.period),
                        func.sum(func.cast(Payslip.read.is_(False), type_=Payslip.year.type)),
                    )
                    .where(Payslip.person_key.in_(by_key))
                    .group_by(Payslip.person_key)
                )
            ).all():
                out[by_key[key or ""]].update({"ultima_nomina": last, "nominas_no_leidas": int(unread or 0)})
        if "documentos_firmados" in fields and by_key:
            for key, count in (
                await db.execute(
                    select(SignedDocument.person_key, func.count())
                    .where(SignedDocument.person_key.in_(by_key))
                    .group_by(SignedDocument.person_key)
                )
            ).all():
                out[by_key[key or ""]]["documentos_firmados"] = int(count)
    return out


def _base(e: Employee, field: str, today: date) -> Any:
    return {
        "puesto": e.position,
        "departamento": e.department,
        "responsable": e.manager_name,
        "activo": "Sí" if e.active else "No",
        "edad": age(e.birth_date, today),
        "email": e.email,
        "telefono": e.phone,
        "nacionalidad": e.nationality,
        "codigo_empleado": e.employee_code,
        "cumpleanos": f"{e.birth_date.day:02d}/{e.birth_date.month:02d}" if e.birth_date else None,
    }.get(field)


def datos_de_personas(deps: Deps) -> Tool:
    async def handler(p: CruceParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        people = await _employees(deps, p, ctx)
        if people is None:
            return no_population()
        fields = list(dict.fromkeys(p.campos))
        extra = await _extra(deps, people, set(fields), today)
        rows = [
            [e.name, *[extra[e.sp_id].get(f, _base(e, f, today)) for f in fields]]
            for e in sorted(people, key=lambda x: x.name)
        ]
        items = [dict(zip(["persona", *fields], r, strict=True)) for r in rows]
        summary: dict[str, Any] = {"personas": len(rows), "campos": fields}
        if len(items) <= 60:
            summary["detalle"] = items
        return ToolResult(
            ToolStatus.OK, summary, table("Datos cruzados", ["Persona", *[LABELS[f] for f in fields]], rows)
        )

    return Tool(
        "datos_de_personas",
        "Cruza un grupo de personas (el resultado anterior, otro anterior con «resultado», o empleado_ids) con "
        "datos de otros dominios: puesto, departamento, responsable, edad, contacto, turno de hoy, saldo y "
        "próximas vacaciones, última nómina y documentos firmados. Úsalo para «de esos, ¿qué puesto tienen / "
        "cuánto saldo les queda / quién trabaja hoy?».",
        CruceParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
    )
