"""Selección ↔ plantilla: ¿algún candidato ya trabaja aquí, o es un antiguo empleado que vuelve a presentarse?"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Candidate, Employee
from mia.modules.rrhh.common import Deps, fmt_date, table
from mia.modules.rrhh.curriculums.tools import person_identity
from mia.text import normalize_key


class CruceCandidatosParams(BaseModel):
    departamento: str | None = Field(default=None, description="Departamento de la candidatura (opcional)")
    situacion: Literal["empleados_actuales", "antiguos_empleados", "ambos"] = "ambos"


def candidatos_y_plantilla(deps: Deps) -> Tool:
    async def handler(p: CruceCandidatosParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            stmt = select(Candidate)
            if p.departamento:
                stmt = stmt.where(Candidate.department_key.like(f"%{normalize_key(p.departamento)}%"))
            candidates = list((await db.scalars(stmt)).all())
            employees = list((await db.scalars(select(Employee))).all())
        by_mail = {e.email.lower(): e for e in employees if e.email}
        by_name: dict[str, list[Employee]] = {}
        for e in employees:
            by_name.setdefault(e.name_key, []).append(e)
        found: dict[str, dict[str, Any]] = {}
        for c in candidates:
            hit, how = (by_mail.get((c.email or "").lower()), "email")
            if hit is None and len(same := by_name.get(c.name_key, [])) == 1:
                hit, how = same[0], "nombre"
            if hit is None:
                continue
            if (p.situacion == "empleados_actuales" and not hit.active) or (
                p.situacion == "antiguos_empleados" and hit.active
            ):
                continue
            row = found.setdefault(
                person_identity(c),
                {
                    "persona": hit.name,
                    "situacion": "Empleado activo" if hit.active else "Antiguo empleado (inactivo)",
                    "puesto": hit.position,
                    "departamento": hit.department,
                    "coincide_por": how,
                    "candidaturas": [],
                },
            )
            row["candidaturas"].append(
                {"departamento": c.department, "estado": c.status, "fecha": fmt_date(c.applied_on)}
            )
        items = sorted(found.values(), key=lambda r: (r["situacion"], r["persona"]))
        summary = {
            "personas": len(items),
            "empleados_actuales": sum(1 for r in items if r["situacion"] == "Empleado activo"),
            "antiguos_empleados": sum(1 for r in items if r["situacion"] != "Empleado activo"),
            "candidaturas_revisadas": len(candidates),
            "nota": "«coincide_por: nombre» es coincidencia por nombre único: confírmala antes de darla por cierta.",
            "coincidencias": items[:60],
        }
        rows = [
            [
                r["persona"],
                r["situacion"],
                r["puesto"],
                r["departamento"],
                "; ".join(f"{c['departamento']} · {c['estado']}" for c in r["candidaturas"]),
                r["coincide_por"],
            ]
            for r in items
        ]
        return ToolResult(
            ToolStatus.OK if items else ToolStatus.NOT_FOUND,
            summary,
            table(
                "Candidatos que son o fueron empleados",
                ["Persona", "Situación", "Puesto", "Departamento", "Candidaturas", "Coincide por"],
                rows,
            ),
        )

    return Tool(
        "candidatos_y_plantilla",
        "Cruza las candidaturas con la plantilla: qué candidatos ya son empleados o son antiguos empleados que "
        "vuelven a presentarse (por email o por nombre único), con su puesto y las candidaturas que tienen.",
        CruceCandidatosParams,
        handler,
        permission=Permission.CURRICULUMS_LEER,
        audit_resource="curriculums",
    )
