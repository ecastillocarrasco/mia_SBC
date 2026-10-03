"""Consulta cruzada componible: criterios de varios dominios sobre las mismas personas.

«Empleados de cocina que están de vacaciones la semana que viene y tienen saldo negativo», «camareras de
pisos con turno de noche mañana», «quién cumple años este mes en recepción», «cuántos de baja hay por
puesto», «personas sin la nómina de agosto»… Cada criterio produce un conjunto de personas; el resultado
es su intersección, y sobre él se lista, se cuenta o se agrupa. La población es la plantilla activa
(POB-001) salvo que se pida expresamente lo contrario.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolResult, ToolStatus
from mia.data import Employee, Payslip, ShiftDay, SignedDocument, Vacation, VacationBalance
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.analitica.cruces import LABELS, Campo, _base, _extra
from mia.modules.rrhh.common import (
    OPERATIONAL_VACATION_STATES,
    ActivosParams,
    CohortParams,
    Deps,
    Periodo,
    department_problem,
    no_population,
    population_label,
    population_state,
    previous_population,
    resolve_department,
    table,
    wants_previous,
)
from mia.modules.rrhh.empleados.tools import age
from mia.modules.rrhh.turnos.tools import starts_in
from mia.text import normalize_key

MAX_ROWS = 200
Que = Literal[
    "de_vacaciones",
    "de_baja",
    "con_permiso",
    "con_asuntos_propios",
    "con_ausencia",
    "trabaja",
    "descansa",
    "sin_turno_publicado",
    "saldo_menor_que",
    "saldo_mayor_que",
    "nominas_sin_leer",
    "sin_nomina_del_periodo",
    "con_documento",
    "sin_documento",
    "cumple_anios_en",
    "edad_entre",
]
DESCRIPTIONS: dict[str, str] = {
    "de_vacaciones": "está de vacaciones (solicitud aceptada) en el periodo",
    "de_baja": "está de baja (Baja/IT) en el periodo",
    "con_permiso": "tiene un permiso en el periodo",
    "con_asuntos_propios": "tiene asuntos propios en el periodo",
    "con_ausencia": "tiene alguna ausencia (baja, permiso, vacaciones o asuntos propios) en el periodo",
    "trabaja": "trabaja en el periodo (valor = franja mañana/tarde/noche, opcional)",
    "descansa": "descansa en el periodo",
    "sin_turno_publicado": "no tiene ningún turno publicado en el periodo",
    "saldo_menor_que": "saldo de vacaciones actual menor que valor (días)",
    "saldo_mayor_que": "saldo de vacaciones actual mayor que valor (días)",
    "nominas_sin_leer": "tiene al menos valor nóminas sin leer (por defecto 1)",
    "sin_nomina_del_periodo": "no tiene nómina ordinaria del mes valor (AAAA-MM)",
    "con_documento": "tiene un documento firmado cuyo tipo contiene valor",
    "sin_documento": "NO tiene un documento firmado cuyo tipo contiene valor",
    "cumple_anios_en": "cumple años en el mes valor (1-12) o entre desde y hasta",
    "edad_entre": "edad entre A y B años (valor «30-40»)",
}


class Condicion(BaseModel):
    que: Que = Field(description="Criterio (ver descripción de la herramienta)")
    valor: str | float | None = Field(default=None, description="Valor del criterio si lo necesita")
    desde: date | None = Field(default=None, description="Inicio del periodo del criterio (por defecto hoy)")
    hasta: date | None = Field(default=None, description="Fin del periodo (por defecto igual que desde)")
    negar: bool = Field(default=False, description="true para «que NO …»")


class ConsultaParams(CohortParams, ActivosParams, Periodo):
    departamento: str | None = None
    puesto: str | None = Field(default=None, description="Parte del puesto: «camarera», «cocinero»…")
    nacionalidad: str | None = None
    responsable: str | None = Field(default=None, description="Parte del nombre del responsable directo")
    condiciones: list[Condicion] = Field(default_factory=list, description="Criterios que deben cumplirse TODOS")
    operacion: Literal["listar", "contar", "agrupar"] = "listar"
    agrupar_por: Literal["departamento", "puesto", "nacionalidad", "responsable", "franja_de_edad"] | None = None
    campos: list[Campo] = Field(
        default_factory=lambda: ["puesto", "departamento"],  # type: ignore[arg-type]
        description="Columnas a mostrar",
    )
    limite: int = Field(default=100, ge=1, le=MAX_ROWS)


def _period(c: Condicion, default_from: date, default_to: date) -> tuple[date, date]:
    start = c.desde or default_from
    return start, c.hasta or (c.desde and start) or default_to


async def _by_shift(
    db: Any, people: list[Employee], kinds: tuple[str, ...], lo: date, hi: date, *, franja: str | None = None
) -> set[int]:
    keys = {e.person_key: e.sp_id for e in people if e.person_key}
    if not keys:
        return set()
    rows = (
        await db.scalars(
            select(ShiftDay).where(
                ShiftDay.person_key.in_(keys), ShiftDay.day.between(lo, hi), ShiftDay.kind.in_(kinds)
            )
        )
    ).all()
    if franja in ("mañana", "tarde", "noche"):
        rows = [s for s in rows if starts_in(s, franja)]
    return {keys[s.person_key] for s in rows if s.person_key}


def _age_range(value: Any) -> tuple[int, int]:
    low, _, high = str(value or "0-120").partition("-")
    return int(float(low or 0)), int(float(high or 120))


async def _matching(db: Any, people: list[Employee], c: Condicion, today: date) -> set[int] | None:  # noqa: PLR0911
    """Personas (sp_id) que cumplen un criterio; None si el criterio no se reconoce."""
    lo, hi = _period(c, today, today)
    by_mail = {e.email.lower(): e.sp_id for e in people if e.email}
    by_key = {e.person_key: e.sp_id for e in people if e.person_key}
    if c.que in {"de_baja", "con_permiso", "con_asuntos_propios", "con_ausencia", "trabaja", "descansa"}:
        kinds = {
            "de_baja": (ShiftKind.BAJA,),
            "con_permiso": (ShiftKind.PERMISO,),
            "con_asuntos_propios": (ShiftKind.ASUNTOS_PROPIOS,),
            "trabaja": (ShiftKind.TRABAJO,),
            "descansa": (ShiftKind.DESCANSO,),
            "con_ausencia": (ShiftKind.BAJA, ShiftKind.VACACIONES, ShiftKind.PERMISO, ShiftKind.ASUNTOS_PROPIOS),
        }[c.que]
        return await _by_shift(
            db, people, kinds, lo, hi, franja=normalize_key(str(c.valor)) if c.que == "trabaja" else None
        )
    if c.que == "sin_turno_publicado":
        return {e.sp_id for e in people} - await _by_shift(
            db,
            people,
            tuple(v for k, v in vars(ShiftKind).items() if k.isupper() and v != ShiftKind.SIN_PUBLICAR),
            lo,
            hi,
        )
    if c.que == "de_vacaciones":
        rows = (
            await db.scalars(
                select(Vacation.employee_email).where(
                    Vacation.start_date <= hi,
                    Vacation.end_date >= lo,
                    func.lower(Vacation.status).in_(sorted(OPERATIONAL_VACATION_STATES)),
                    func.lower(Vacation.request_type) == "vacaciones",
                    func.lower(Vacation.employee_email).in_(by_mail),
                )
            )
        ).all()
        return {by_mail[m.lower()] for m in rows if m}
    if c.que in {"saldo_menor_que", "saldo_mayor_que"}:
        limit = float(c.valor or 0)
        cmp = (
            VacationBalance.current_balance < limit
            if c.que == "saldo_menor_que"
            else VacationBalance.current_balance > limit
        )
        rows = (
            await db.scalars(
                select(VacationBalance.employee_email).where(
                    VacationBalance.year == today.year, cmp, func.lower(VacationBalance.employee_email).in_(by_mail)
                )
            )
        ).all()
        return {by_mail[m.lower()] for m in rows if m}
    if c.que == "nominas_sin_leer":
        rows = (
            await db.execute(
                select(Payslip.person_key, func.count())
                .where(Payslip.person_key.in_(by_key), Payslip.read.is_(False))
                .group_by(Payslip.person_key)
            )
        ).all()
        minimum = int(float(c.valor or 1))
        return {by_key[k] for k, n in rows if k and n >= minimum}
    if c.que == "sin_nomina_del_periodo":
        period = str(c.valor or f"{today.year}-{today.month:02d}")
        have = (
            await db.scalars(
                select(Payslip.person_key).where(
                    Payslip.person_key.in_(by_key), Payslip.period == period, Payslip.special.is_(False)
                )
            )
        ).all()
        return {e.sp_id for e in people} - {by_key[k] for k in have if k}
    if c.que in {"con_documento", "sin_documento"}:
        rows = (
            await db.execute(
                select(SignedDocument.person_key, SignedDocument.doc_type).where(SignedDocument.person_key.in_(by_key))
            )
        ).all()
        wanted = normalize_key(str(c.valor or ""))
        have = {by_key[k] for k, t in rows if k and wanted in normalize_key(t)}
        return have if c.que == "con_documento" else {e.sp_id for e in people} - have
    if c.que == "cumple_anios_en":
        if c.desde or c.hasta:
            start, end = (c.desde or today), (c.hasta or c.desde or today)
            span = {(start.month, start.day)} | {
                (d.month, d.day) for d in (start.fromordinal(o) for o in range(start.toordinal(), end.toordinal() + 1))
            }
            return {e.sp_id for e in people if e.birth_date and (e.birth_date.month, e.birth_date.day) in span}
        month = int(float(c.valor or today.month))
        return {e.sp_id for e in people if e.birth_date and e.birth_date.month == month}
    if c.que == "edad_entre":
        low, high = _age_range(c.valor)
        return {e.sp_id for e in people if (a := age(e.birth_date, today)) is not None and low <= a <= high}
    return None


def _band(e: Employee, today: date) -> str:
    years = age(e.birth_date, today)
    if years is None:
        return "Sin fecha de nacimiento"
    lo = min(years // 10 * 10, 60)
    return f"{lo}+ años" if lo == 60 else f"{lo}-{lo + 9} años"


def _group_key(e: Employee, by: str, today: date) -> str:
    return {
        "departamento": e.department,
        "puesto": e.position,
        "nacionalidad": e.nationality,
        "responsable": e.manager_name,
        "franja_de_edad": _band(e, today),
    }.get(by) or "Sin dato"


async def _base_people(
    deps: Deps, p: ConsultaParams, ctx: ToolContext
) -> tuple[list[Employee] | ToolResult, list[str]]:
    notes: list[str] = []
    async with deps.db.session() as db:
        stmt = select(Employee)
        if not p.incluir_inactivos:
            stmt = stmt.where(Employee.active.is_(True))
        if p.departamento:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento), notes
            if dept.key:
                stmt = stmt.where(Employee.department_key == dept.key)
                notes.append(f"departamento {dept.name}")
        if wants_previous(p, ctx):
            if (previous := previous_population(ctx, p.resultado)) is None:
                return no_population(), notes
            stmt = stmt.where(Employee.sp_id.in_(previous["empleado_ids"]))
            notes.append(f"de: {previous.get('etiqueta')}")
        people = list((await db.scalars(stmt.order_by(Employee.name))).all())
    for attr, wanted, label in (
        ("position", p.puesto, "puesto"),
        ("nationality", p.nacionalidad, "nacionalidad"),
        ("manager_name", p.responsable, "responsable"),
    ):
        if wanted:
            people = [e for e in people if normalize_key(wanted) in normalize_key(getattr(e, attr))]
            notes.append(f"{label} «{wanted}»")
    return people, notes


def consulta_cruzada(deps: Deps) -> Tool:
    async def handler(p: ConsultaParams, ctx: ToolContext) -> ToolResult:
        today = ctx.now.date()
        base, criteria = await _base_people(deps, p, ctx)
        if isinstance(base, ToolResult):
            return base
        people = base
        default_lo, default_hi = p.resolve(today)
        unknown: list[str] = []
        funnel: list[dict[str, Any]] = [{"criterio": "partida (base)", "personas": len(people)}]
        async with deps.db.session() as db:
            for c in p.condiciones:
                cond = (
                    c.model_copy(update={"desde": c.desde or p.desde, "hasta": c.hasta or p.hasta})
                    if not c.desde
                    else c
                )
                matched = await _matching(db, people, cond, today)
                if matched is None:
                    unknown.append(c.que)
                    continue
                keep = {e.sp_id for e in people} - matched if c.negar else matched
                people = [e for e in people if e.sp_id in keep]
                funnel.append({"criterio": ("NO " if c.negar else "") + DESCRIPTIONS[c.que], "personas": len(people)})
                start, end = _period(cond, default_lo, default_hi)
                criteria.append(
                    ("NO " if c.negar else "")
                    + DESCRIPTIONS[c.que]
                    + (
                        f" [{start.isoformat()}–{end.isoformat()}]"
                        if c.que.startswith(("de_", "con_a", "con_p", "trab", "desc", "sin_t"))
                        else ""
                    )
                    + (f" ({c.valor})" if c.valor not in (None, "") and c.que not in {"trabaja"} else "")
                )
        summary: dict[str, Any] = {
            "poblacion": population_label(p.incluir_inactivos),
            "criterios": criteria or ["toda la plantilla"],
            "total": len(people),
            **({"criterios_no_reconocidos": unknown} if unknown else {}),
        }
        if len(funnel) > 1:
            # Dónde se pierde el resultado: sirve para explicar un «ninguno» o un número pequeño.
            summary["embudo"] = funnel
        state = population_state(f"consulta cruzada ({'; '.join(criteria) or 'plantilla'})", people)
        if p.operacion == "contar":
            return ToolResult(ToolStatus.OK, summary, None, state)
        if p.operacion == "agrupar" and p.agrupar_por:
            groups = Counter(_group_key(e, p.agrupar_por, today) for e in people)
            summary["agrupado_por"] = p.agrupar_por
            summary["grupos"] = dict(groups.most_common())
            return ToolResult(
                ToolStatus.OK,
                summary,
                table(
                    f"Por {p.agrupar_por.replace('_', ' ')}",
                    [p.agrupar_por.replace("_", " ").capitalize(), "Personas"],
                    [[k, v] for k, v in groups.most_common()],
                ),
                state,
            )
        shown = people[: p.limite]
        fields = list(dict.fromkeys(p.campos))
        extra = await _extra(deps, shown, set(fields), today)
        rows = [[e.name, *[extra[e.sp_id].get(f, _base(e, f, today)) for f in fields]] for e in shown]
        if len(rows) <= 60:
            summary["detalle"] = [dict(zip(["persona", *fields], r, strict=True)) for r in rows]
        if len(people) > len(shown):
            summary["nota"] = f"Se muestran {len(shown)} de {len(people)}."
        return ToolResult(
            ToolStatus.OK, summary, table("Consulta cruzada", ["Persona", *[LABELS[f] for f in fields]], rows), state
        )

    listing = "; ".join(f"{k}: {v}" for k, v in DESCRIPTIONS.items())
    return Tool(
        "consulta_cruzada",
        "Combina criterios de VARIOS dominios sobre las mismas personas y lista, cuenta o agrupa el resultado. "
        "Base: departamento, puesto, nacionalidad, responsable (o el resultado anterior). Criterios (todos deben "
        f"cumplirse; negar=true para «que no»): {listing}. Sirve para «empleados de X que están de vacaciones "
        "y tienen saldo negativo», «quién trabaja de noche mañana en Y», «cuántos de baja por puesto», «quién "
        "cumple años este mes», «personas sin la nómina de agosto». Por defecto, plantilla activa.",
        ConsultaParams,
        handler,
        permission=Permission.EMPLEADOS_LEER,
        audit_resource="empleados",
        timeout_seconds=45,
    )
