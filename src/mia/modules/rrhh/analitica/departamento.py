"""Ficha 360 de un departamento: plantilla, hoy, ausencias, vacaciones, nóminas y ETT en una sola respuesta."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, OrgUnit, Payslip, ShiftDay, TtTimesheet, VacationBalance
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import Deps, department_problem, resolve_department, table
from mia.modules.rrhh.empleados.tools import age

ABSENT = (ShiftKind.BAJA, ShiftKind.VACACIONES, ShiftKind.PERMISO, ShiftKind.ASUNTOS_PROPIOS)


class DepartamentoParams(BaseModel):
    departamento: str = Field(description="Departamento")


def ficha_departamento(deps: Deps) -> Tool:
    async def handler(p: DepartamentoParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK or not dept.key:
                return department_problem(dept, p.departamento)
            staff = list(
                (
                    await db.scalars(
                        select(Employee).where(Employee.active.is_(True), Employee.department_key == dept.key)
                    )
                ).all()
            )
            keys = {e.person_key for e in staff if e.person_key}
            mails = {e.email.lower() for e in staff if e.email}
            managers: list[Any] = list(
                (await db.scalars(select(OrgUnit.managers).where(OrgUnit.department_key == dept.key))).all()
            )
            kinds = Counter(
                k
                for (k,) in (
                    await db.execute(select(ShiftDay.kind).where(ShiftDay.day == today, ShiftDay.person_key.in_(keys)))
                ).all()
            )
            upcoming = (
                await db.execute(
                    select(func.count(func.distinct(ShiftDay.person_key))).where(
                        ShiftDay.person_key.in_(keys),
                        ShiftDay.kind.in_(ABSENT),
                        ShiftDay.day.between(today + timedelta(days=1), today + timedelta(days=7)),
                    )
                )
            ).scalar_one()
            balances = [
                b
                for b in (
                    await db.scalars(
                        select(VacationBalance).where(
                            VacationBalance.year == today.year, func.lower(VacationBalance.employee_email).in_(mails)
                        )
                    )
                ).all()
                if b.current_balance is not None
            ]
            unread = (
                await db.execute(select(func.count()).where(Payslip.person_key.in_(keys), Payslip.read.is_(False)))
            ).scalar_one()
            ett = (
                await db.execute(
                    select(func.count(func.distinct(TtTimesheet.worker_name))).where(
                        TtTimesheet.day == today, TtTimesheet.department_key == dept.key
                    )
                )
            ).scalar_one()
        ages = [a for e in staff if (a := age(e.birth_date, today)) is not None]
        names = sorted(
            {str(m.get("nombre") if isinstance(m, dict) else m) for group in managers for m in (group or [])}
        )
        summary: dict[str, Any] = {
            "departamento": dept.name,
            "plantilla_activa": len(staff),
            "por_puesto": dict(Counter(e.position or "Sin dato" for e in staff).most_common(12)),
            "responsables": names,
            "edad_media": round(sum(ages) / len(ages), 1) if ages else None,
            "hoy": {
                "trabajando": kinds.get(ShiftKind.TRABAJO, 0),
                "descansan": kinds.get(ShiftKind.DESCANSO, 0),
                "vacaciones": kinds.get(ShiftKind.VACACIONES, 0),
                "baja": kinds.get(ShiftKind.BAJA, 0),
                "permiso_o_asuntos_propios": kinds.get(ShiftKind.PERMISO, 0) + kinds.get(ShiftKind.ASUNTOS_PROPIOS, 0),
                "sin_turno_publicado": max(0, len(keys) - sum(kinds.values())),
            },
            "personas_con_ausencia_proximos_7_dias": upcoming,
            "vacaciones": {
                "saldo_medio": round(sum(b.current_balance or 0 for b in balances) / len(balances), 1)
                if balances
                else None,
                "con_saldo_negativo": sum(1 for b in balances if (b.current_balance or 0) < 0),
            },
            "personas_con_nominas_sin_leer": int(unread),
            "ett_con_boletin_hoy": int(ett),
        }
        flat = [
            [k, v]
            for k, v in {
                "Plantilla activa": summary["plantilla_activa"],
                "Trabajando hoy": summary["hoy"]["trabajando"],
                "De baja hoy": summary["hoy"]["baja"],
                "De vacaciones hoy": summary["hoy"]["vacaciones"],
                "Ausencias próximos 7 días": upcoming,
                "Saldo medio de vacaciones": summary["vacaciones"]["saldo_medio"],
                "Saldos negativos": summary["vacaciones"]["con_saldo_negativo"],
                "Personas con nóminas sin leer": int(unread),
                "ETT hoy": int(ett),
            }.items()
        ]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Departamento · {dept.name}", ["Indicador", "Valor"], flat),
            {"foco_departamento": dept.name},
        )

    return Tool(
        "ficha_departamento",
        "Ficha 360 de un departamento: plantilla activa por puesto, responsables, edad media, situación de hoy "
        "(trabajando, descanso, vacaciones, baja, sin turno), ausencias de la próxima semana, saldo de "
        "vacaciones, nóminas sin leer y ETT de hoy. Para «cuéntame cómo está Pisos» o «resumen de Cocina».",
        DepartamentoParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
    )
