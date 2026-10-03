"""Empleados y organización: búsqueda, ficha, plantilla y estructura."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, OrgUnit, Payslip, ShiftDay, SignedDocument, Vacation, VacationBalance
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import (
    MAX_ROWS_FOR_MODEL,
    CohortParams,
    Deps,
    PersonaParams,
    confirmed_vacations,
    department_problem,
    find_people,
    fmt_date,
    focus_person,
    no_population,
    person_problem,
    person_summary,
    population_state,
    previous_population,
    resolve_department,
    resolve_person,
    table,
    wants_previous,
)
from mia.modules.rrhh.turnos.periods import AbsencePeriod, absence_periods
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
    incluir_inactivos: bool = Field(default=False, description="Incluir personas que ya no están en plantilla")


def buscar(deps: Deps) -> Tool:
    async def handler(p: BuscarParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            people = await find_people(db, p.nombre, include_inactive=p.incluir_inactivos)
        if not people:
            return ToolResult(ToolStatus.NOT_FOUND, {"mensaje": f"Nadie encaja con «{p.nombre}»."})
        summary: dict[str, Any] = {
            "total": len(people),
            "personas": [person_summary(e) for e in people[:MAX_ROWS_FOR_MODEL]],
        }
        state = focus_person(people[0]) if len(people) == 1 else {}
        status = ToolStatus.OK
        if len(people) > 1:
            # Si el usuario pedía datos de UNA persona, no se elige por él (fallo real: «el turno de Ana»).
            status = ToolStatus.AMBIGUOUS
            summary["mensaje"] = (
                f"Hay {len(people)} personas que encajan. Si el usuario pedía datos de una sola, "
                "pregúntale cuál antes de consultar nada; si pedía la lista, muéstrala."
            )
        rows = [[e.name, e.department, e.position, "Sí" if e.active else "No"] for e in people]
        return ToolResult(
            status,
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
COMPONENTS = ("empleados", "turnos", "vacaciones", "nominas", "documentos_firmados")


async def build_profile(db: AsyncSession, e: Employee, today: date, *, full_history: bool = False) -> dict[str, Any]:
    """Ficha 360: hoy, semana, próximos hitos, datos laborales, organización, vacaciones,
    bajas, nóminas y documentación (la misma estructura que el sistema anterior).

    Cada componente se compone de forma aislada: si una fuente falla o no está al día, la
    ficha entera no se cae, se marca «calidad: parcial» y se añade una alerta con el
    componente afectado (misma semántica que el «Employee360» del sistema anterior).
    """
    alerts: list[dict[str, str]] = []
    week_start = today - timedelta(days=today.weekday())
    shifts: list[ShiftDay] = []
    current_absence = None
    sick_year: list[AbsencePeriod] = []
    if e.person_key:
        shifts = list(
            (
                await db.scalars(
                    select(ShiftDay)
                    .where(
                        ShiftDay.person_key == e.person_key,
                        ShiftDay.day.between(week_start, today + timedelta(days=21)),
                    )
                    .order_by(ShiftDay.day)
                )
            ).all()
        )
        now_periods = await absence_periods(db, lo=today, hi=today, person_keys=[e.person_key])
        current_absence = now_periods[0] if now_periods else None
        sick_year = await absence_periods(
            db, lo=date(today.year, 1, 1), hi=today, kinds=(ShiftKind.BAJA,), person_keys=[e.person_key]
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
            select(VacationBalance).where(VacationBalance.employee_email == e.email, VacationBalance.year == today.year)
        )
    units = list((await db.scalars(select(OrgUnit).where(OrgUnit.department_key == e.department_key))).all())
    managers = sorted({m["name"] for u in units for m in u.managers or [] if m.get("name")})
    slips: list[Payslip] = []
    docs: list[SignedDocument] = []
    if e.person_key:
        slips = list(
            (
                await db.scalars(select(Payslip).where(Payslip.person_key == e.person_key, Payslip.year == today.year))
            ).all()
        )
        docs = list((await db.scalars(select(SignedDocument).where(SignedDocument.person_key == e.person_key))).all())
    by_day = {s.day: s for s in shifts}
    today_shift = by_day.get(today)
    accepted = await confirmed_vacations(db, vacations)
    upcoming: list[dict[str, Any]] = []
    if current_absence is not None:
        back = current_absence.return_shift
        upcoming.append(
            {
                "hito": f"fin de {current_absence.kind}",
                "fecha": current_absence.end.isoformat(),
                "vuelve": back.day.isoformat() if back else "sin turno publicado",
            }
        )
    for v in accepted[:2]:
        if v.start_date and v.start_date > today:
            upcoming.append(
                {
                    "hito": v.request_type or "Vacaciones",
                    "fecha": v.start_date.isoformat(),
                    "hasta": v.end_date.isoformat() if v.end_date else None,
                }
            )
    next_rest = next((s for s in shifts if s.day > today and s.kind == ShiftKind.DESCANSO), None)
    if next_rest:
        upcoming.append({"hito": "próximo descanso", "fecha": next_rest.day.isoformat()})
    ordinary_months = {s.month for s in slips if s.month and not s.special}
    missing_months = [m for m in range(1, today.month) if m not in ordinary_months]
    sick_days = sum(p.days_within(date(today.year, 1, 1), today) for p in sick_year)
    if not e.person_key:
        alerts.append({"componente": "turnos", "motivo": "sin DNI/NIE con el que cruzar turnos, bajas y nóminas"})
    if not units:
        alerts.append({"componente": "organizacion", "motivo": "sin sección de departamento localizada"})
    profile: dict[str, Any] = {
        "empleado_id": e.sp_id,
        "nombre": e.name,
        "activo": e.active,
        "hoy": {
            "turno": {"tipo": today_shift.kind, "horario": today_shift.raw_value}
            if today_shift
            else "sin turno publicado",
            "ausencia_en_curso": (
                {
                    "tipo": current_absence.kind,
                    "desde": current_absence.start.isoformat(),
                    "dias_hasta_hoy": (today - current_absence.start).days + 1,
                }
                if current_absence
                else None
            ),
        },
        "semana_actual": [
            {
                "fecha": d.isoformat(),
                "tipo": by_day[d].kind if d in by_day else "Sin publicar",
                "horario": by_day[d].raw_value if d in by_day else None,
            }
            for d in (week_start + timedelta(days=i) for i in range(7))
        ],
        "proximos_hitos": upcoming,
        "ficha_laboral": {
            "puesto": e.position,
            "departamento": e.department,
            "codigo_empleado": e.employee_code,
            "edad": age(e.birth_date, today),
            "email": e.email,
            "telefono": e.phone,
            "cuenta": e.account,
            "nacionalidad": e.nationality,
        },
        "organizacion": {
            "responsable_directo": e.manager_name,
            "responsables_del_departamento": managers,
            "secciones_del_departamento": sorted({u.section for u in units if u.section}),
        },
        "vacaciones": {
            "saldo_actual": balance.current_balance if balance else None,
            "saldo_total": balance.total_balance if balance else None,
            "aceptadas_proximas": [
                {
                    "desde": fmt_date(v.start_date),
                    "hasta": fmt_date(v.end_date),
                    "dias": v.total_days,
                    "tipo": v.request_type,
                }
                for v in accepted[:3]
            ],
            "pendientes": sum(1 for v in vacations if normalize_key(v.status) == PENDING),
        },
        "bajas_este_anio": {
            "periodos": len(sick_year),
            "dias": sick_days,
            "ultima": (
                {"desde": sick_year[-1].start.isoformat(), "hasta": sick_year[-1].end.isoformat()}
                if sick_year
                else None
            ),
        },
        "documentacion": {
            "nominas_este_anio": len(slips),
            "nominas_no_leidas": sum(1 for s in slips if s.read is False),
            "meses_sin_nomina": missing_months,
            "documentos_por_tipo": dict(Counter(d.doc_type for d in docs)),
        },
        "indicadores": {
            "saldo_vacaciones": balance.current_balance if balance else None,
            "dias_de_baja_este_anio": sick_days,
            "nominas_no_leidas": sum(1 for s in slips if s.read is False),
            "documentos_firmados": len(docs),
        },
        "acciones_rapidas": [
            "Muéstrame sus turnos",
            "Muéstrame sus vacaciones",
            "Muéstrame sus bajas",
            "Muéstrame sus nóminas",
            "Muéstrame sus documentos",
            "Genera la ficha en PDF",
        ],
    }
    profile["alertas_calidad"] = alerts
    profile["calidad"] = "con_observaciones" if alerts else "sin_incidencias"
    if full_history:
        profile["historico"] = {
            "vacaciones": [
                {
                    "desde": fmt_date(v.start_date),
                    "hasta": fmt_date(v.end_date),
                    "dias": v.total_days,
                    "tipo": v.request_type,
                    "estado": v.status,
                }
                for v in vacations
            ],
            "bajas": [{"desde": p.start.isoformat(), "hasta": p.end.isoformat(), "dias": p.days} for p in sick_year],
            "nominas": [{"periodo": s.period, "especial": s.special, "leida": s.read} for s in slips],
            "documentos": [{"tipo": d.doc_type, "documento": d.file_name} for d in docs],
        }
    return profile


class FichaParams(PersonaParams):
    detalle: bool = Field(default=False, description="true para el histórico completo de cada componente")


def ficha(deps: Deps) -> Tool:
    async def handler(p: FichaParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            profile = await build_profile(db, e, today, full_history=p.detalle)
            fresh = await deps.freshness(db, *COMPONENTS, f"saldo_vacaciones_{today.year}")
        card = {**profile, **fresh}
        return ToolResult(
            ToolStatus.OK,
            card,
            {"type": "employee_360", "title": f"Ficha 360 · {e.name}", **card},
            focus_person(e),
        )

    return Tool(
        "ficha_empleado",
        "Ficha 360 de una persona: hoy, semana, próximos hitos, datos laborales, organización, vacaciones, "
        "saldo, bajas del año, nóminas y documentación. Usa empleado_id si está en el foco. Con detalle=true, "
        "el histórico completo de cada bloque.",
        FichaParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
    )


# ------------------------------------------------------------------ plantilla
def age_stats(people: list[Employee], today: date) -> dict[str, Any]:
    """Edad media global y por departamento, sobre quien tiene fecha de nacimiento (como el sistema anterior)."""
    ages = [(e, a) for e in people if (a := age(e.birth_date, today)) is not None]
    if not ages:
        return {}
    by_dept: dict[str, list[int]] = defaultdict(list)
    for e, a in ages:
        by_dept[e.department or "Sin dato"].append(a)
    return {
        "edad_media": round(sum(a for _, a in ages) / len(ages), 1),
        "edad_calculada_sobre": len(ages),
        "sin_fecha_de_nacimiento": len(people) - len(ages),
        "edad_media_por_departamento": {
            d: {"edad_media": round(sum(v) / len(v), 1), "personas": len(v)}
            for d, v in sorted(by_dept.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
        },
    }


class PlantillaParams(CohortParams):
    departamento: str | None = Field(default=None, description="Departamento (opcional)")
    puesto: str | None = Field(default=None, description="Puesto o parte del nombre del puesto (opcional)")
    estado: Literal["activos", "inactivos", "todos"] = Field(
        default="activos", description="Por defecto solo activos (regla POB-001)"
    )
    agrupar_por: Literal["departamento", "puesto", "nacionalidad"] | None = Field(
        default=None,
        description="Recuento por departamento, puesto o nacionalidad (se muestra agrupado, sin listar a todos)",
    )
    incluir_edad: bool = Field(
        default=False, description="true SOLO si preguntan por la edad (media, por departamento…)"
    )
    listar: bool = Field(default=False, description="true para listar también a las personas cuando se agrupa")


def plantilla(deps: Deps) -> Tool:
    async def handler(p: PlantillaParams, ctx: ToolContext) -> ToolResult:
        async with deps.db.session() as db:
            if p.puesto and not p.departamento:
                # Fallo real: «empleados de Pisos» llegó como puesto=pisos (112) en vez de departamento (136).
                as_department = await resolve_department(db, p.puesto)
                if as_department.status is ToolStatus.OK and as_department.key == normalize_key(p.puesto):
                    p.departamento, p.puesto = p.puesto, None
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            stmt = select(Employee)
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
            if p.estado != "todos":
                stmt = stmt.where(Employee.active.is_(p.estado == "activos"))
            if wants_previous(p, ctx):
                previous = previous_population(ctx, p.resultado)
                if previous is None:
                    return no_population()
                stmt = stmt.where(Employee.sp_id.in_(previous["empleado_ids"]))
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
            field = {"departamento": "department", "puesto": "position", "nacionalidad": "nationality"}[p.agrupar_por]
            counts = Counter(getattr(e, field) or "Sin dato" for e in people)
            summary["por_" + p.agrupar_por] = dict(counts.most_common())
        if p.incluir_edad:
            summary.update(age_stats(people, ctx.now.date()))
        if len(people) <= MAX_ROWS_FOR_MODEL:
            summary["personas"] = [person_summary(e) for e in people]
        state: dict[str, Any] = {"foco_departamento": dept.name} if dept.name else {}
        state.update(population_state(f"plantilla {p.estado} {dept.name or ''}".strip(), people))
        if p.agrupar_por and not p.listar:
            # Un recuento por categorías se presenta agrupado (y se dibuja como gráfico), no como 343 nombres.
            label = p.agrupar_por.capitalize()
            grouped = summary["por_" + p.agrupar_por]
            return ToolResult(
                ToolStatus.OK,
                summary,
                table(f"Empleados por {p.agrupar_por}", [label, "Personas"], list(grouped.items())),
                state,
            )
        rows = [[e.name, e.department, e.position] for e in people]
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(f"Plantilla ({p.estado})", ["Nombre", "Departamento", "Puesto"], rows, total=len(people)),
            state,
        )

    return Tool(
        "plantilla",
        "Cuenta y lista la plantilla por departamento o puesto (edad media solo con incluir_edad). "
        "Por defecto solo activos; usa estado='inactivos' o 'todos' solo si el usuario lo pide.",
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
