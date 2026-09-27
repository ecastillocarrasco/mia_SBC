"""Empleados y organización: búsqueda, ficha, plantilla y estructura."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, OrgUnit, ShiftDay, Vacation, VacationBalance
from mia.domains.common import (
    MAX_ROWS_FOR_MODEL,
    Deps,
    PersonaParams,
    department_problem,
    find_people,
    fmt_date,
    focus_person,
    person_problem,
    person_summary,
    resolve_department,
    resolve_person,
    table,
)
from mia.text import normalize_key

ACCEPTED = "aceptada"
PENDING = "pendiente"


def age(birth: date | None, today: date) -> int | None:
    if birth is None:
        return None
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


# ------------------------------------------------------------------ buscar
class BuscarParams(BaseModel):
    nombre: str = Field(description="Nombre o parte del nombre")
    incluir_inactivos: bool = Field(
        default=False, description="Incluir personas que ya no están en plantilla"
    )


def buscar(deps: Deps) -> Tool:
    async def handler(p: BuscarParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            people = await find_people(db, p.nombre, include_inactive=p.incluir_inactivos)
        if not people:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": f"Nadie encaja con «{p.nombre}»."})
        summary = {"total": len(people), "personas": [person_summary(e) for e in people[:MAX_ROWS_FOR_MODEL]]}
        state = focus_person(people[0]) if len(people) == 1 else {}
        rows = [[e.name, e.department, e.position, "Sí" if e.active else "No"] for e in people]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table("Personas", ["Nombre", "Departamento", "Puesto", "Activo"], rows),
            state,
        )

    return Tool(
        "buscar_empleado",
        "Busca personas por nombre. Úsala para localizar a alguien o resolver ambigüedades.",
        BuscarParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
    )


# ------------------------------------------------------------------ ficha 360
def ficha(deps: Deps) -> Tool:
    async def handler(p: PersonaParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            shift = None
            if e.person_key:
                shift = await db.scalar(
                    select(ShiftDay).where(ShiftDay.person_key == e.person_key, ShiftDay.day == today)
                )
            vacations: list[Vacation] = []
            balance = None
            if e.email:
                vacations = list(
                    (
                        await db.scalars(
                            select(Vacation)
                            .where(Vacation.employee_email == e.email, Vacation.end_date >= today)
                            .order_by(Vacation.start_date)
                        )
                    ).all()
                )
                balance = await db.scalar(
                    select(VacationBalance).where(
                        VacationBalance.employee_email == e.email, VacationBalance.year == today.year
                    )
                )
            dept_managers: list[str] = []
            if e.department_key:
                units = (
                    await db.scalars(select(OrgUnit).where(OrgUnit.department_key == e.department_key))
                ).all()
                dept_managers = sorted({m["name"] for u in units for m in u.managers or [] if m.get("name")})
            fresh = await deps.freshness(
                db, "empleados", "turnos", "vacaciones", f"saldo_vacaciones_{today.year}"
            )
        accepted = [v for v in vacations if normalize_key(v.status) == ACCEPTED]
        card: dict[str, Any] = {
            "empleado_id": e.sp_id,
            "nombre": e.name,
            "activo": e.active,
            "departamento": e.department,
            "puesto": e.position,
            "responsable_directo": e.manager_name,
            "responsables_del_departamento": dept_managers,
            "edad": age(e.birth_date, today),
            "email": e.email,
            "telefono": e.phone,
            "turno_hoy": (
                {"tipo": shift.kind, "horario": shift.raw_value, "comentario": shift.comment}
                if shift
                else None
            ),
            "vacaciones_en_curso_o_proximas": [
                {
                    "desde": fmt_date(v.start_date),
                    "hasta": fmt_date(v.end_date),
                    "dias": v.total_days,
                    "tipo": v.request_type,
                }
                for v in accepted[:3]
            ],
            "solicitudes_pendientes": sum(1 for v in vacations if normalize_key(v.status) == PENDING),
            "saldo_vacaciones": balance.current_balance if balance else None,
            **fresh,
        }
        return ToolResult(ToolStatus.OK, card, {"type": "employee_card", **card}, focus_person(e))

    return Tool(
        "ficha_empleado",
        "Ficha completa de una persona: puesto, departamento, responsable, turno de hoy, vacaciones "
        "próximas y saldo. Usa empleado_id si está en el foco.",
        PersonaParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
    )


# ------------------------------------------------------------------ plantilla
class PlantillaParams(BaseModel):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    puesto: str | None = Field(default=None, description="Puesto o parte del nombre del puesto (opcional)")
    estado: Literal["activos", "inactivos", "todos"] = Field(
        default="activos", description="Por defecto solo activos (regla POB-001)"
    )
    agrupar_por: Literal["departamento", "puesto"] | None = None


def plantilla(deps: Deps) -> Tool:
    async def handler(p: PlantillaParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(Employee)
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
            if p.estado != "todos":
                stmt = stmt.where(Employee.active.is_(p.estado == "activos"))
            people = list((await db.scalars(stmt.order_by(Employee.name))).all())
            fresh = await deps.freshness(db, "empleados")
        if p.puesto:
            wanted = normalize_key(p.puesto)
            people = [e for e in people if wanted in normalize_key(e.position)]
        summary: dict[str, Any] = {
            "total": len(people),
            "estado": p.estado,
            "departamento": dept.name,
            "puesto": p.puesto,
            **fresh,
        }
        if p.agrupar_por:
            field = "department" if p.agrupar_por == "departamento" else "position"
            counts = Counter(getattr(e, field) or "Sin dato" for e in people)
            summary["por_" + p.agrupar_por] = dict(counts.most_common())
        if len(people) <= MAX_ROWS_FOR_MODEL:
            summary["personas"] = [person_summary(e) for e in people]
        state = {"foco_departamento": dept.name} if dept.name else {}
        rows = [[e.name, e.department, e.position] for e in people]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Plantilla ({p.estado})", ["Nombre", "Departamento", "Puesto"], rows, total=len(people)),
            state,
        )

    return Tool(
        "plantilla",
        "Cuenta y lista la plantilla por departamento o puesto. Por defecto solo activos; usa "
        "estado='inactivos' o 'todos' solo si el usuario lo pide.",
        PlantillaParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
    )


# ------------------------------------------------------------------ estructura
class EstructuraParams(BaseModel):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")


def estructura(deps: Deps) -> Tool:
    async def handler(p: EstructuraParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(OrgUnit).order_by(OrgUnit.department, OrgUnit.section)
            if p.departamento:
                stmt = stmt.where(OrgUnit.department_key.like(f"%{normalize_key(p.departamento)}%"))
            units = list((await db.scalars(stmt)).all())
        if not units:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": "No hay secciones para ese departamento."})
        rows: list[dict[str, Any]] = [
            {
                "departamento": u.department,
                "seccion": u.section,
                "responsables": [m.get("name") for m in u.managers or [] if m.get("name")],
            }
            for u in units
        ]
        return ToolResult(
            ToolStatus.OK,
            {"departamentos": sorted({u.department for u in units if u.department}), "secciones": rows},
            table(
                "Estructura",
                ["Departamento", "Sección", "Responsables"],
                [[r["departamento"], r["seccion"], ", ".join(r["responsables"])] for r in rows],
            ),
        )

    return Tool(
        "estructura_departamentos",
        "Departamentos, sus secciones y responsables.",
        EstructuraParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (buscar, ficha, plantilla, estructura):
        registry.register(factory(deps))
