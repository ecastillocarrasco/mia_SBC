"""Nóminas: qué nóminas existen, de qué periodo y si se han leído.

NOM-002: el contenido de las nóminas (importes) no se lee ni se guarda. mIA
informa de existencia, periodo y lectura; para importes hay que abrir la nómina.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import date
from typing import Any

from pydantic import Field
from sqlalchemy import and_, or_, select

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.data import Employee, Payslip
from mia.ingestion.mappers.docs import _month_in_text as month_in_text
from mia.modules.rrhh.common import (
    MAX_ROWS_FOR_MODEL,
    CohortParams,
    Deps,
    PersonaParams,
    department_problem,
    document_entry,
    focus_person,
    no_population,
    person_problem,
    population_state,
    previous_population,
    resolve_department,
    resolve_person,
    table,
    wants_previous,
)
from mia.modules.rrhh.content import MAX_BYTES, content_unavailable, pdf_lines
from mia.modules.rrhh.nominas.parser import parse_payslip
from mia.text import normalize_key

RULE = "Metadatos (existencia, periodo, lectura). Para importes: nomina_importes o evolucion_nominas (NOM-002)."


def _belongs(e: Employee) -> Any:
    """La carpeta (DNI seudonimizado) manda; UsuarioNomina solo se usa si la nómina no está en carpeta."""
    conditions = []
    if e.person_key:
        conditions.append(Payslip.person_key == e.person_key)
    if e.email:
        conditions.append(and_(Payslip.person_key.is_(None), Payslip.employee_email == e.email))
    return or_(*conditions) if conditions else Payslip.sp_id < 0


_EXTRA_WORD = re.compile(r"(?:^|[_\-\s])extra(?:[_\-\s.]|$)", re.IGNORECASE)
_MONTHLY_NAME = re.compile(r"^20\d{2}[-_](?:1[0-2]|0?[1-9])(?=[_-]|\.|$)", re.IGNORECASE)


def document_kind(slip: Payslip) -> str:  # noqa: PLR0911
    """Tipo de documento de la biblioteca Nominas, con la misma prioridad que el sistema anterior.

    1) la columna MesNomina (con «extra» → paga extra; con un mes real → nómina mensual) y
    2) el nombre del fichero (certificado de retenciones, bolsa de vacaciones, «extra», «AAAA-MM…»).
    """
    label = normalize_key(slip.label)
    if label:
        if "extra" in label or "extraordinari" in label:
            return "paga extra"
        if month_in_text(slip.label) is not None:
            return "nómina mensual"
    name = normalize_key(slip.file_name)
    if "certificado retenciones" in name or "certificado de retenciones" in name:
        return "certificado de retenciones"
    if "bolsa vacaciones" in name or "bolsa de vacaciones" in name:
        return "bolsa de vacaciones"
    if _EXTRA_WORD.search(name):
        return "paga extra"
    if _MONTHLY_NAME.match(slip.file_name or ""):
        return "nómina mensual"
    if not slip.file_name and not slip.label:  # sin nombre ni MesNomina: lo único que queda es lo ya interpretado
        return "paga extra" if slip.special else ("nómina mensual" if slip.month else "otro documento")
    return "otro documento"


class NominasPersonaParams(PersonaParams):
    anio: int | None = Field(default=None, description="Año concreto; sin año, TODO el histórico disponible")
    solo_no_leidas: bool = False


def nominas_persona(deps: Deps) -> Tool:
    async def handler(p: NominasPersonaParams, ctx: ToolContext) -> ToolResult:
        year = p.anio
        async with deps.db.session() as db:
            match = await resolve_person(db, p)
            if match.employee is None:
                return person_problem(match, p.nombre)
            e = match.employee
            stmt = select(Payslip).where(_belongs(e))
            if year:
                stmt = stmt.where(Payslip.year == year)
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
        check_year = year or ctx.now.year
        months = {r.month for r in rows if r.month and not r.special and r.year == check_year}
        last_month = ctx.now.month - 1 if check_year == ctx.now.year else 12
        missing = [m for m in range(1, max(0, last_month) + 1) if m not in months]
        latest = max((r.period for r in rows if r.period), default=None)
        summary: dict[str, Any] = {
            "persona": e.name,
            "anio": year or "todos",
            "total_documentos": len(items),
            "por_tipo": dict(Counter(document_kind(r) for r in rows).most_common()),
            "por_anio": dict(sorted(Counter(r.year or 0 for r in rows).items(), reverse=True)),
            "mas_reciente": latest,
            f"meses_sin_nomina_{check_year}_hasta_el_mes_pasado": missing,
            "no_leidas": sum(1 for r in rows if r.read is False),
            "regla": RULE,
            **fresh,
        }
        if len(items) <= 40:
            summary["nominas"] = items
        else:
            summary["ultimas"] = items[-24:]
        view = table(
            f"Nóminas {year or 'histórico'} · {e.name}",
            ["Periodo", "Concepto", "Especial", "Leída", "Enlace"],
            [[i["periodo"], i["concepto"], "Sí" if i["paga_especial"] else "", i["leida"], i["enlace"]] for i in items],
        )
        if ctx.user.has(Permission.NOMINAS_IMPORTES):  # el PDF contiene importes: solo con ese permiso
            view["documents"] = [
                document_entry(
                    "nomina", r.sp_id, r.label or r.period or "Nómina", subtitle=document_kind(r), date=r.period
                )
                for r in reversed(rows[-36:])
            ]
        return ToolResult(ToolStatus.OK, summary, view, focus_person(e))

    return Tool(
        "nominas_persona",
        "Documentos de nómina de una persona (por defecto, todo el histórico): recuento por tipo (mensuales, "
        "pagas extra, certificados de retenciones, bolsas de vacaciones) y año, lectura y meses que faltan. "
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
            if wants_previous(p, ctx):
                if (previous := previous_population(ctx, p.resultado)) is None:
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


class AnomaliasNominasParams(CohortParams):
    periodo: str = Field(description="Mes AAAA-MM a revisar")
    departamento: str | None = None


def anomalias_nominas(deps: Deps) -> Tool:
    async def handler(p: AnomaliasNominasParams, ctx: ToolContext) -> ToolResult:
        try:
            year, month = (int(x) for x in p.periodo.split("-", 1))
            date(year, month, 1)
        except ValueError:
            return ToolResult(ToolStatus.INVALID_ARGUMENTS, "El periodo debe ser AAAA-MM")
        async with deps.db.session() as db:
            dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            emp_stmt = select(Employee).where(Employee.active.is_(True))
            if dept.key:
                emp_stmt = emp_stmt.where(Employee.department_key == dept.key)
            if wants_previous(p, ctx):
                if (previous := previous_population(ctx, p.resultado)) is None:
                    return no_population()
                emp_stmt = emp_stmt.where(Employee.sp_id.in_(previous["empleado_ids"]))
            employees = list((await db.scalars(emp_stmt)).all())
            slips = list(
                (await db.scalars(select(Payslip).where(Payslip.period == p.periodo))).all()
            )
            fresh = await deps.freshness(db, "nominas", "empleados")

        # Construir índices
        by_folder: dict[str, list[Payslip]] = {}
        by_email: dict[str, list[Payslip]] = {}
        for s in slips:
            if s.person_key:
                by_folder.setdefault(s.person_key, []).append(s)
            elif s.employee_email:
                by_email.setdefault(s.employee_email, []).append(s)

        issues: list[dict[str, Any]] = []

        # 1. Duplicados: más de una nómina ordinaria para la misma persona en el periodo
        for emp in employees:
            key = emp.person_key
            matched = (by_folder.get(key or "") or []) + (by_email.get(emp.email or "") if not key else [])
            ordinary = [s for s in matched if not s.special]
            if len(ordinary) > 1:
                issues.append({
                    "tipo": "duplicado",
                    "persona": emp.name,
                    "departamento": emp.department,
                    "nominas": len(ordinary),
                    "detalle": "más de una nómina ordinaria en el mismo período",
                })

        # 2. Faltantes: empleados activos sin ninguna nómina en el periodo
        missing_emp = []
        for emp in employees:
            key = emp.person_key
            has = bool((by_folder.get(key or "")) or (by_email.get(emp.email or "") if not key else None))
            if not has:
                missing_emp.append(emp)

        # 3. Huérfanos: nóminas sin correspondencia con ningún empleado activo
        active_keys = {e.person_key for e in employees if e.person_key}
        active_emails = {e.email for e in employees if e.email}
        orphan_slips = [
            s for s in slips
            if (s.person_key and s.person_key not in active_keys)
            or (not s.person_key and s.employee_email and s.employee_email not in active_emails)
        ]

        n_issues = len(issues) + len(missing_emp) + len(orphan_slips)
        summary: dict[str, Any] = {
            "periodo": p.periodo,
            "departamento": dept.name or "toda la plantilla activa",
            "plantilla_activa": len(employees),
            "nominas_en_el_periodo": len(slips),
            "total_anomalias": n_issues,
            "duplicados": len(issues),
            "faltantes": len(missing_emp),
            "huerfanos": len(orphan_slips),
            **fresh,
        }
        if issues:
            summary["detalle_duplicados"] = issues[:20]
        if missing_emp and len(missing_emp) <= MAX_ROWS_FOR_MODEL:
            summary["personas_sin_nomina"] = [e.name for e in missing_emp]
        if orphan_slips:
            summary["detalle_huerfanos"] = [
                {"archivo": s.file_name, "email": s.employee_email} for s in orphan_slips[:20]
            ]

        rows = (
            [["Duplicado", i["persona"], i["departamento"], i["detalle"]] for i in issues]
            + [["Faltante", e.name, e.department, "sin nómina en el periodo"] for e in missing_emp[:40]]
            + [["Huérfano", s.file_name or "—", "—", s.employee_email or "sin email"] for s in orphan_slips[:20]]
        )
        return ToolResult(
            ToolStatus.OK,
            summary,
            table(
                f"Anomalías nóminas {p.periodo}",
                ["Tipo", "Persona / Archivo", "Departamento", "Detalle"],
                rows,
            ),
            population_state(f"con anomalía en {p.periodo}", missing_emp) if missing_emp else None,
        )

    return Tool(
        "anomalias_nominas",
        "Detecta anomalías en las nóminas de un mes: empleados sin nómina (faltantes), nóminas duplicadas "
        "para la misma persona y nóminas sin correspondencia con un empleado activo (huérfanas). "
        "Basado en metadatos, sin leer PDFs.",
        AnomaliasNominasParams,
        handler,
        permission=Permission.NOMINAS_LEER,
        audit_resource="nominas",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    for factory in (nominas_persona, nominas_periodo, anomalias_nominas):
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
        "Importes de una nómina leídos del PDF en el momento: devengado, deducciones, líquido, IRPF "
        "(porcentaje e importe), conceptos salariales (salario base, pluses, complementos…) y coste "
        "de empresa con SS. Responde «¿cuánto cobró X en julio?», «¿qué retención IRPF tiene?», "
        "«¿qué conceptos tiene la nómina de X?».",
        ImportesParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=45,
    )


class EvolucionParams(PersonaParams):
    anio: int | None = Field(default=None, description="Año (por defecto, el actual)")
    comparar_con_anio_anterior: bool = Field(
        default=False,
        description="True para incluir también el año anterior y mostrar la variación interanual",
    )


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
            prev_slips: list[Payslip] = []
            if p.comparar_con_anio_anterior:
                prev_slips = list(
                    (
                        await db.scalars(
                            select(Payslip).where(_belongs(e), Payslip.year == year - 1).order_by(Payslip.period)
                        )
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
        summary: dict[str, Any] = {
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
        if p.comparar_con_anio_anterior and prev_slips:
            prev_results = list(await asyncio.gather(*(_read_amounts(deps, s) for s in prev_slips[:16])))
            prev_ord = [r for r in prev_results if not r.get("paga_especial") and r.get("importes", {}).get("liquido")]
            prev_medio = round(sum(r["importes"]["liquido"] for r in prev_ord) / len(prev_ord), 2) if prev_ord else None
            curr_medio = summary["liquido_medio_ordinario"]
            variacion = None
            if prev_medio and curr_medio:
                variacion = round(curr_medio - prev_medio, 2)
                variacion_pct = round((variacion / prev_medio) * 100, 2)
            else:
                variacion_pct = None
            summary["comparacion_anio_anterior"] = {
                "anio_anterior": year - 1,
                "liquido_medio_ordinario_anterior": prev_medio,
                "liquido_medio_ordinario_actual": curr_medio,
                "variacion_euros": variacion,
                "variacion_pct": variacion_pct,
                "nominas_anio_anterior": prev_results,
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
        "Evolución de los importes de las nóminas de una persona en un año (y comparaciones entre meses). "
        "Con comparar_con_anio_anterior=True incluye también el año anterior y la variación interanual: "
        "úsalo para «¿cuánto ha subido el sueldo de X respecto al año pasado?».",
        EvolucionParams,
        handler,
        permission=Permission.NOMINAS_IMPORTES,
        audit_resource="nominas_importes",
        timeout_seconds=90,
    )


def register_amounts(registry: ToolRegistry, deps: Deps) -> None:
    from mia.modules.rrhh.informes.jobs import informe_economico_en_segundo_plano  # noqa: PLC0415
    from mia.modules.rrhh.nominas.analisis_economico import analisis_economico_nominas  # noqa: PLC0415
    from mia.modules.rrhh.nominas.estadisticas import estadisticas_salariales, ranking_salarial  # noqa: PLC0415

    for factory in (
        nomina_importes,
        evolucion_nominas,
        estadisticas_salariales,
        ranking_salarial,
        analisis_economico_nominas,
    ):
        registry.register(factory(deps))
    # Solo se ofrece si el worker en segundo plano está activo (MIA_JOBS__ENABLED=true, ver
    # src/mia/main.py): un trabajo encolado sin ningún worker que lo reclame se quedaría "en cola"
    # para siempre — nunca un botón que promete algo que el despliegue actual no puede cumplir. Y
    # solo si, además, la ejecución asíncrona de informes sensibles está explícitamente permitida
    # (Fase I, cierre de seguridad: MIA_JOBS__ALLOW_SENSITIVE_ASYNC=true) — mientras no exista una
    # fuente verificable de autorizaciones vigentes, el modelo ni siquiera debe ver esta herramienta.
    jobs_settings = getattr(deps.settings, "jobs", None)
    if getattr(jobs_settings, "enabled", False) and getattr(jobs_settings, "allow_sensitive_async", False):
        registry.register(informe_economico_en_segundo_plano(deps))
