"""Informes PDF/Excel a partir del último resultado en tabla de la conversación,
y generación autónoma del informe ejecutivo de RRHH para dirección."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from mia.assets import resolve_logo
from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.conversation.tools import LAST_TABLE, remember_table
from mia.text import normalize_key
from mia.data import Report
from mia.data.models import _uuid
from mia.diagnostics import EventStage
from mia.diagnostics import emit as diag_emit
from mia.modules.rrhh.common import Deps, department_problem, resolve_department
from mia.modules.rrhh.informes.document import Document, to_document
from mia.modules.rrhh.informes.render import RENDERERS
from mia.reporting.narrative_generation import generate_narrative_block
from mia.reporting.content_composer import MissingReportEvidence, compose_for_request
from mia.reporting.comparisons import (
    explicit_month_comparison, merge_payroll_comparison, remembered_comparison,
)
from mia.reporting.planner import planner


class InformeParams(BaseModel):
    formato: Literal["pdf", "xlsx", "pptx", "html"] = Field(description="pdf, xlsx (Excel), pptx (PowerPoint) o html")
    titulo: str | None = Field(default=None, description="Título (por defecto, el de la tabla)")
    incluir_detalle: bool = Field(
        default=True,
        description=(
            "Incluir la tabla de detalle con todos los registros individuales. "
            "Pasar False si el usuario pide solo el resumen, el gráfico o los totales "
            "sin el listado completo de personas o filas."
        ),
    )
    incluir_grafico: bool = Field(
        default=True,
        description=(
            "Incluir gráfico automático de distribución si los datos tienen desglose por categorías "
            "(por departamento, por tipo…). True por defecto."
        ),
    )
    incluir_narrativa: bool = Field(
        default=False,
        description=(
            "Añadir una sección de hallazgos redactada por el modelo, verificada frase a frase contra "
            "los datos reales antes de publicarse (nunca una cifra sin respaldo). False por defecto: "
            "pásalo a True solo si el usuario pide expresamente un análisis o unas conclusiones, no para "
            "una simple exportación de tabla."
        ),
    )


def _render(fmt: str, document: Document, generated: datetime, logo: Path | None) -> bytes:
    return RENDERERS[fmt](document, generated, resolve_logo(logo))


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def _build_report_result(
    deps: Deps,
    ctx: ToolContext,
    presentation: dict,
    *,
    formato: str,
    titulo: str | None,
    incluir_detalle: bool,
    incluir_grafico: bool,
    incluir_narrativa: bool,
    tool_name: str,
) -> ToolResult:
    """Construye, renderiza y persiste un informe a partir de una presentación ya calculada (tabla,
    panel, resultado de ``analisis_economico_nominas``…). Compartido por ``generar_informe`` y por la
    redirección interna de ``generar_informe_ejecutivo`` — nunca dos copias del mismo renderizado."""
    settings = deps.settings.reports if deps.settings else None
    directory = Path(settings.directory if settings else "informes")
    ttl = timedelta(hours=settings.ttl_hours if settings else 24)
    document = to_document(presentation, include_detail=incluir_detalle, include_chart=incluir_grafico)
    if titulo:
        document.title = titulo
    title = document.title
    if incluir_narrativa:
        # Fase F (integración LLM): se usa deps.llm, el MISMO proveedor que ya usa el resto de mIA
        # (ya envuelto por el Privacy Gateway en build_llm_provider() — nunca un segundo camino
        # hacia el proveedor), y se verifica contra los datos reales antes de añadirse — nunca una
        # afirmación sin comprobar.
        #
        # Privacidad contextual (revisión de la Fase F): "nombre" en el resumen es el patrón ya usado
        # por herramientas de sujeto individual (p. ej. ficha_empleado) que YA comprobaron el permiso
        # para esa persona EXACTA antes de construir su resumen — esa autorización, ya tomada, es lo
        # único que se reutiliza aquí; un informe agregado (sin "nombre") nunca autoriza ningún nombre
        # propio en la narrativa (fail-closed, ver authorized_subjects en generate_narrative_block).
        summary = presentation.get("__summary__") or {}
        subject = summary.get("nombre")
        authorized_subjects = frozenset({subject}) if isinstance(subject, str) and subject.strip() else frozenset()
        # Coherencia temporal (revisión de la Fase F): "periodo_interpretado" es la clave ya usada por
        # el motor analítico (p. ej. analisis_economico_nominas) para el periodo real del informe — se
        # pasa como contexto explícito y se verifica contra el campo estructurado que cada hecho declara,
        # nunca analizando la prosa libre con expresiones regulares.
        expected_period = summary.get("periodo_interpretado")
        narrative = await generate_narrative_block(
            deps.llm,
            title=title,
            backend_summary=summary,
            authorized_subjects=authorized_subjects,
            expected_period=expected_period if isinstance(expected_period, str) else None,
            llm_settings=getattr(deps.settings, "llm", None),
        )
        if narrative is not None:
            document.blocks.append(narrative)
    try:
        document = await compose_for_request(
            document, ctx.user_message, deps.llm,
            llm_settings=getattr(deps.settings, "llm", None),
        )
    except MissingReportEvidence as exc:
        return ToolResult(
            ToolStatus.INVALID_ARGUMENTS,
            {"mensaje": "No hay evidencia suficiente para cumplir toda la petición; no se genera un informe incompleto.",
             "requisitos_pendientes": exc.missing},
        )
    logo_path = settings.logo_path if settings else None
    content = await asyncio.to_thread(_render, formato, document, ctx.now, logo_path)
    report_id = _uuid()
    path = directory / f"{report_id}.{formato}"
    await asyncio.to_thread(_write, path, content)
    safe = re.sub(r"[^\w\- ]+", "", title).strip()[:60] or "informe"
    file_name = f"{safe}.{formato}"
    # Reautorización en la descarga (Fase I, cierre de seguridad): un informe construido a partir de
    # `analisis_economico_nominas` exige NOMINAS_IMPORTES también en el momento de descargarlo, con el
    # usuario que esté autenticado ENTONCES — nunca solo la propiedad, que es lo único que comprobaba
    # antes `GET /api/reports/{id}`. El resto de dominios queda exactamente igual que siempre (`None`).
    required_permission = (
        Permission.NOMINAS_IMPORTES.value
        if presentation.get("__source_tool__") in _PAYROLL_SOURCE_TOOLS
        or "analisis_economico_nominas" in tool_name
        else None
    )
    async with deps.db.session() as db:
        db.add(
            Report(
                id=report_id,
                user_id=ctx.user.user_id,
                title=title,
                format=formato,
                file_name=file_name,
                path=str(path),
                required_permission=required_permission,
                expires_at=ctx.now + ttl,
            )
        )
    url = f"/api/reports/{report_id}"
    # Trazabilidad (sección 22/requisito 5 del Bloque II): el propio `report_id` ya queda persistido
    # en la tabla `reports` (user_id/título/formato/fechas, sin datos personales del contenido); esto
    # solo lo enlaza con la traza de diagnóstico de ESTE turno, si está activa — nunca guarda cifras
    # ni nombres, solo metadatos estructurales.
    diag_emit(
        EventStage.REPORT_GENERATION,
        data={"report_id": report_id, "formato": formato, "secciones": len(document.blocks), "tool": tool_name},
    )
    return ToolResult(
        ToolStatus.OK,
        {
            "informe": file_name,
            "secciones": len(document.blocks),
            "enlace": url,
            "caduca_en_horas": int(ttl.total_seconds() // 3600),
        },
        {"type": "download", "title": title, "format": formato, "url": url, "file_name": file_name},
    )


_PAYROLL_SOURCE_TOOLS = frozenset({"analisis_economico_nominas"})


def _contextual_payroll_concept(state: dict) -> str | None:
    """El último resultado económico puede aportar el concepto, nunca cifras o periodos nuevos.

    Útil para seguimientos como «PDF de la comparación agosto 2025 y 2026»,
    donde el usuario no repite «nóminas», pero la tabla reciente está auditada
    como resultado salarial. El motor SIEMPRE vuelve a consultar ambos meses.
    """
    last = state.get(LAST_TABLE)
    if not isinstance(last, dict) or last.get("__source_tool__") not in _PAYROLL_SOURCE_TOOLS:
        return None
    summary = last.get("__summary__") or {}
    if not isinstance(summary, dict):
        return None
    label = normalize_key(summary.get("concepto_economico", ""))
    return {
        "coste empresa": "coste_empresa",
        "devengado bruto": "devengado",
        "liquido neto": "liquido",
    }.get(label)
"""Herramientas cuyo resultado SÍ puede contener coste salarial real. Si la petición original pide un
dato económico de nómina pero la última tabla no viene de ninguna de estas, exportarla sería entregar
un informe semánticamente distinto del que se pidió (ver sección 15/incidencia de costes por
departamento) — se rechaza en vez de exportar en silencio."""


def generar(deps: Deps) -> Tool:
    async def handler(p: InformeParams, ctx: ToolContext) -> ToolResult:
        # Si hay dos meses explícitos de nóminas, no exportar la última
        # ejecución aislada como si fuera una comparativa. Recalcular ambos
        # periodos por la MISMA herramienta autorizada y consolidarlos.
        if ctx.user_message:
            request_plan = planner.plan(ctx.user_message, user=ctx.user, today=ctx.now.date())
            has_payroll = any(m.field.domain == "payroll" for m in request_plan.metrics)
            comparison = explicit_month_comparison(ctx.user_message)
            remembered = None
            if comparison is None and not any(m.field.domain != "payroll" for m in request_plan.metrics):
                remembered = remembered_comparison(ctx.session_state, ctx.user_message)
                if remembered:
                    comparison = remembered[0]
            if has_payroll and request_plan.compare and not comparison and len(set(re.findall(r"\b20\d{2}\b", ctx.user_message))) >= 2:
                return ToolResult(
                    ToolStatus.INVALID_ARGUMENTS,
                    {"mensaje": (
                        "La petición compara dos ejercicios, pero no se han identificado dos meses concretos "
                        "con año. No exportaré un solo periodo como si fuera una comparativa. "
                        "Indica ambos meses explícitamente, por ejemplo 'agosto 2025 y agosto 2026'."
                    )},
                )
            contextual_concept = _contextual_payroll_concept(ctx.session_state)
            if comparison and (has_payroll or remembered or
                               (contextual_concept and not request_plan.metrics)):
                payroll_names = (remembered[1] if remembered else
                                 {m.field.name for m in request_plan.metrics if m.field.domain == "payroll"})
                concepto = (_infer_concepto(payroll_names) if payroll_names else contextual_concept)
                return await _run_economic_comparison(
                    deps, ctx, comparison, formato=p.formato, titulo=p.titulo,
                    incluir_detalle=p.incluir_detalle, incluir_grafico=p.incluir_grafico,
                    incluir_narrativa=p.incluir_narrativa, concepto=concepto,
                )
        presentation = ctx.session_state.get(LAST_TABLE)
        if not presentation:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                "No hay ningún resultado reciente (tabla, panel o ficha) para el informe.",
            )
        export_meta = presentation.get("__export_meta__") or {}
        if export_meta.get("truncated"):
            names = ", ".join(item["table"] for item in export_meta.get("tables", []))
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS,
                {"mensaje": (
                    "No se puede generar un informe íntegro desde el resultado abreviado de la sesión "
                    f"({names}). Vuelve a ejecutar la consulta con una fuente de exportación completa; "
                    "no se publicará un documento que omita filas sin advertirlo."
                )},
            )
        # Fase F, punto 1 (revisado: "procedencia del análisis económico"): el plan de la petición no
        # es solo una sugerencia para el LLM — se valida contra la EJECUCIÓN que de verdad produjo lo
        # que se va a exportar (reutiliza el MISMO ReportPlanner, nunca un segundo planificador). Solo
        # se aplica al dominio "payroll": es el único con un incidente real demostrado; generalizarlo
        # sin verificar los demás dominios arriesgaría bloquear exportaciones legítimas (ver limitación
        # documentada en ADVANCED_REPORTING_PROGRESS.md).
        if ctx.user_message:
            plan = planner.plan(ctx.user_message, user=ctx.user, today=ctx.now.date())
            payroll_names = {m.field.name for m in plan.metrics if m.field.domain == "payroll"}
            if payroll_names:
                # Atado a la tabla que se va a exportar (``__source_tool__``, puesto por
                # ``remember_table()`` junto a ESTA presentación concreta) — nunca a "la última
                # herramienta llamada en el turno" (``LAST_CALL``), que puede haber cambiado por una
                # herramienta auxiliar posterior sin presentación propia (sin tocar esta tabla) y
                # rechazaría así un informe legítimo por una causa ajena a sus datos.
                source_tool = presentation.get("__source_tool__")
                if source_tool not in _PAYROLL_SOURCE_TOOLS:
                    campos = ", ".join(sorted(payroll_names))
                    return ToolResult(
                        ToolStatus.INVALID_ARGUMENTS,
                        {
                            "mensaje": (
                                f"La petición menciona datos económicos de nómina ({campos}), pero el último "
                                "resultado disponible para exportar no viene de 'analisis_economico_nominas'. "
                                "Ejecuta esa herramienta primero con el periodo y concepto correctos, y "
                                "después exporta su resultado — nunca se exporta una tabla que no coincide "
                                "con lo pedido."
                            )
                        },
                    )
                # Periodo: evita aceptar el resultado de OTRA petición anterior (periodo distinto) que
                # siguiera siendo la última tabla en la sesión cuando llega esta nueva petición.
                backend_period = (presentation.get("__summary__") or {}).get("periodo_interpretado")
                if (
                    plan.period
                    and isinstance(backend_period, str)
                    and normalize_key(plan.period.label) != normalize_key(backend_period)
                ):
                    return ToolResult(
                        ToolStatus.INVALID_ARGUMENTS,
                        {
                            "mensaje": (
                                f"La petición pide el periodo «{plan.period.label}», pero el último resultado "
                                f"de 'analisis_economico_nominas' disponible es de «{backend_period}». Ejecuta "
                                "esa herramienta de nuevo con el periodo correcto antes de exportar — nunca se "
                                "exporta el resultado de otro periodo."
                            )
                        },
                    )
        return await _build_report_result(
            deps,
            ctx,
            presentation,
            formato=p.formato,
            titulo=p.titulo,
            incluir_detalle=p.incluir_detalle,
            incluir_grafico=p.incluir_grafico,
            incluir_narrativa=p.incluir_narrativa,
            tool_name="generar_informe",
        )

    return Tool(
        "generar_informe",
        "Genera informes PDF, Excel, PowerPoint y HTML con marca corporativa. Si el usuario "
        "pide comparar nóminas o costes de un mes en dos años, consulta internamente ambos periodos "
        "en la fuente autorizada y produce un ÚNICO informe comparativo; NO exige que los dos "
        "resultados estén activos ni almacenados en la sesión. También permite exportar la "
        "última tabla, panel o ficha ya calculada. Nunca inventes que deben activarse dos "
        "resultados a la vez. Ejemplo: «PDF de costes por departamento de agosto 2025 y 2026».",
        InformeParams,
        handler,
        permission=Permission.INFORMES_GENERAR,
        audit_resource="informes",
        timeout_seconds=600,
    )


# ------------------------------------------------------------------ informe ejecutivo autónomo
class InformeEjecutivoParams(BaseModel):
    desde: date | None = Field(
        default=None,
        description="Inicio del periodo a analizar (por defecto, inicio del mes en curso)",
    )
    hasta: date | None = Field(
        default=None,
        description="Fin del periodo a analizar (por defecto, hoy)",
    )
    departamento: str | None = Field(
        default=None,
        description="Limitar el informe a un departamento concreto; sin valor: toda la empresa",
    )
    formato: Literal["pdf", "xlsx", "pptx", "html"] = Field(
        default="pdf",
        description="Formato del documento: pdf (predeterminado), xlsx, pptx o html",
    )
    titulo: str | None = Field(default=None, description="Título personalizado del informe")


_CONCEPTO_BY_FIELD = {"coste_empresa": "coste_empresa", "total_devengado": "devengado", "liquido": "liquido"}
_CONCEPTO_PRIORITY = ("coste_empresa", "total_devengado", "liquido")


def _infer_concepto(payroll_field_names: set[str]) -> str:
    """Prioriza el concepto económico más completo cuando la petición menciona varios: coste_empresa >
    devengado > líquido (el mismo orden que recomienda la propia descripción de ``analisis_economico_nominas``
    para 'gasto en nóminas'/'coste salarial'). Un campo sin equivalente directo (p. ej. 'irpf') no bloquea
    la redirección: se usa el concepto por defecto de la herramienta económica ('liquido')."""
    for name in _CONCEPTO_PRIORITY:
        if name in payroll_field_names:
            return _CONCEPTO_BY_FIELD[name]
    return "liquido"


async def _run_economic_comparison(
    deps: Deps,
    ctx: ToolContext,
    periods: tuple[str, str],
    *,
    formato: str,
    titulo: str | None,
    incluir_detalle: bool,
    incluir_grafico: bool,
    incluir_narrativa: bool,
    departamento: str | None = None,
    concepto: str = "coste_empresa",
) -> ToolResult:
    """Consulta los dos meses por el ToolRegistry y compone un solo informe.

    No se usa ningún segundo motor, SQL sin autorización, ni restas de grupos
    ocultos. Las consultas usan la misma herramienta real y sus controles NOM-005.
    """
    from mia.llm import ToolCall  # noqa: PLC0415

    registry: ToolRegistry | None = deps.services.get("registry")
    if registry is None:
        return ToolResult(ToolStatus.ERROR, "El registro de herramientas no está disponible.")
    results = []
    for index, period in enumerate(periods):
        call = ToolCall(
            f"reporte-comparativo-{index}",
            "analisis_economico_nominas",
            json.dumps({"periodo": period, "concepto": concepto,
                        "departamento": departamento, "incluir_inactivos": True}),
        )
        execution = await registry.execute(call, ctx)
        if execution.result.status is not ToolStatus.OK:
            return execution.result
        if not isinstance(execution.result.summary, dict):
            return ToolResult(ToolStatus.ERROR, "La fuente económica no devolvió un resumen verificable.")
        results.append(execution.result)
    try:
        presentation, summary = merge_payroll_comparison(
            results[0].summary, results[1].summary, periods,
        )
    except ValueError as exc:
        return ToolResult(ToolStatus.INVALID_ARGUMENTS, {"mensaje": str(exc)})
    presentation["__source_tool__"] = "analisis_economico_nominas"
    presentation["__summary__"] = summary
    remember_table(
        ctx.session_state, presentation,
        getattr(getattr(deps.settings, "reports", None), "max_rows", 5000), summary,
        source_tool="analisis_economico_nominas",
    )
    return await _build_report_result(
        deps, ctx, presentation, formato=formato, titulo=titulo,
        incluir_detalle=incluir_detalle, incluir_grafico=incluir_grafico,
        incluir_narrativa=incluir_narrativa,
        tool_name="generar_informe->analisis_economico_nominas_comparativa",
    )


async def _redirect_to_economic_analysis(
    deps: Deps, ctx: ToolContext, p: InformeEjecutivoParams, lo: date, hi: date, concepto: str
) -> ToolResult:
    """Redirección real (no un mensaje de error): ejecuta `analisis_economico_nominas` a través del
    MISMO `ToolRegistry` que habría usado el LLM, para no saltarse su comprobación de permisos
    (`Permission.NOMINAS_IMPORTES`, distinto del permiso de este informe), su trazado de diagnóstico ni
    su timeout — y renderiza el resultado con el mismo `_build_report_result()` que usa `generar_informe`."""
    from mia.llm import ToolCall  # noqa: PLC0415 — evita un ciclo de import a nivel de módulo

    registry: ToolRegistry | None = deps.services.get("registry")
    if registry is None:  # pragma: no cover — solo si Deps se construye fuera de build_registry()
        return ToolResult(
            ToolStatus.ERROR,
            "No se puede redirigir al análisis económico: el registro de herramientas no está disponible.",
        )
    request_plan = planner.plan(ctx.user_message, user=ctx.user, today=ctx.now.date()) if ctx.user_message else None
    comparison = explicit_month_comparison(ctx.user_message) if request_plan else None
    remembered = None
    if comparison is None and request_plan is not None and not any(
        m.field.domain != "payroll" for m in request_plan.metrics
    ):
        remembered = remembered_comparison(ctx.session_state, ctx.user_message)
        if remembered:
            comparison = remembered[0]
            concepto = _infer_concepto(remembered[1])
    if request_plan and request_plan.compare and not comparison and len(set(re.findall(r"\b20\d{2}\b", ctx.user_message))) >= 2:
        return ToolResult(
            ToolStatus.INVALID_ARGUMENTS,
            {"mensaje": (
                "No se puede generar una comparativa salarial fiable: hay dos ejercicios en la petición "
                "pero no se han identificado dos meses completos. Especifica los dos meses y años."
            )},
        )
    if comparison:
        return await _run_economic_comparison(
            deps, ctx, comparison, formato=p.formato, titulo=p.titulo,
            incluir_detalle=True, incluir_grafico=True, incluir_narrativa=False,
            departamento=p.departamento, concepto=concepto,
        )
    periodo = f"{lo:%Y-%m} a {hi:%Y-%m}"
    eco_call = ToolCall(
        "informe_ejecutivo->analisis_economico_nominas",
        "analisis_economico_nominas",
        json.dumps({"periodo": periodo, "departamento": p.departamento, "concepto": concepto}),
    )
    eco_execution = await registry.execute(eco_call, ctx)
    eco_result = eco_execution.result
    if eco_result.status is not ToolStatus.OK:
        # El propio mensaje de analisis_economico_nominas (sin datos, permiso denegado…) ya es correcto
        # y específico — nunca se sustituye por el informe ejecutivo genérico ni por un error distinto.
        return eco_result
    # Incidencia real (trace mia-20261012-115403-bad97707): el resultado de ESTE informe es un
    # `{"type": "download"}` (ya persistido en disco) — `remember_table()` lo descarta a propósito
    # (no hay nada más que "re-exportar" de un documento ya generado). Pero eso significa que la TABLA
    # real del análisis económico (`eco_result.presentation`, con KPIs/gráficos/departamentos) nunca
    # llegaba a `session_state`, solo vivía en esta variable local — así que una petición posterior en
    # OTRO turno ("exporta a PDF el informe anterior", "ahora en Excel"…) no encontraba nada que
    # exportar (`generar_informe` devolvía `NOT_FOUND`, con ``data``/``presentations`` vacíos: el
    # síntoma exacto de la incidencia). Se recuerda aquí explícitamente — el mismo patrón que ya usa
    # `run_informe_economico_nominas` (Job Manager) por la misma razón.
    max_rows = getattr(getattr(deps.settings, "reports", None), "max_rows", 5000)
    remember_table(
        ctx.session_state, eco_result.presentation, max_rows, eco_result.summary,
        source_tool="analisis_economico_nominas",
    )
    return await _build_report_result(
        deps,
        ctx,
        {**eco_result.presentation, "__source_tool__": "analisis_economico_nominas",
         "__summary__": eco_result.summary},
        formato=p.formato,
        titulo=p.titulo,
        incluir_detalle=True,
        incluir_grafico=True,
        incluir_narrativa=False,
        tool_name="generar_informe_ejecutivo->analisis_economico_nominas",
    )


def generar_ejecutivo(deps: Deps) -> Tool:
    async def handler(p: InformeEjecutivoParams, ctx: ToolContext) -> ToolResult:
        from mia.modules.rrhh.informes.executive import build_executive_report  # noqa: PLC0415

        today = ctx.now.date()
        # Interpretación del periodo: si el usuario no fijó fechas explícitas, no asumir "mes en curso"
        # en silencio cuando su petición sí menciona un periodo reconocible (p. ej. "agosto de 2026") —
        # usar el mismo PeriodEngine ya validado (Fase B) que usa analisis_economico_nominas, en vez de
        # dejar que una fecha mal interpretada por el LLM se pierda sustituyéndose por el mes actual.
        request_plan = planner.plan(ctx.user_message, user=ctx.user, today=today) if ctx.user_message else None
        if p.desde is None and p.hasta is None and request_plan is not None and request_plan.period is not None:
            lo = request_plan.period.start
            hi = request_plan.period.end
        else:
            lo = p.desde or today.replace(day=1)
            hi = p.hasta or today

        # Redirección automática real (incidencia: "comparativa de costes en nóminas por departamento"
        # producía un informe ejecutivo genérico de plantilla/absentismo/vacaciones, sin ningún dato
        # económico, pese a tener el título correcto). Este informe NUNCA calcula coste salarial: si la
        # petición original menciona un campo del dominio "payroll" (coste_empresa, líquido, devengado…),
        # se ejecuta de verdad `analisis_economico_nominas` y se entrega ESE resultado — nunca un error
        # técnico ni una mera indicación de qué herramienta usar.
        if request_plan is not None:
            payroll_names = {m.field.name for m in request_plan.metrics if m.field.domain == "payroll"}
            previous_pair = None
            if not any(m.field.domain != "payroll" for m in request_plan.metrics):
                previous_pair = remembered_comparison(ctx.session_state, ctx.user_message)
            contextual_concept = None
            if (not payroll_names and not previous_pair and not request_plan.metrics
                    and explicit_month_comparison(ctx.user_message)):
                contextual_concept = _contextual_payroll_concept(ctx.session_state)
            if payroll_names or previous_pair or contextual_concept:
                if previous_pair and not payroll_names:
                    payroll_names = previous_pair[1]
                concepto = _infer_concepto(payroll_names) if payroll_names else contextual_concept
                return await _redirect_to_economic_analysis(deps, ctx, p, lo, hi, concepto)

        dept_key: str | None = None
        dept_name: str | None = None
        if p.departamento:
            async with deps.db.session() as db:
                dept = await resolve_department(db, p.departamento)
            if dept.status is not ToolStatus.OK:
                return department_problem(dept, p.departamento)
            dept_key = dept.key
            dept_name = dept.name

        document = await build_executive_report(deps, lo, hi, today, dept_key, dept_name)
        if p.titulo:
            document.title = p.titulo
        try:
            document = await compose_for_request(
                document, ctx.user_message, deps.llm,
                llm_settings=getattr(deps.settings, "llm", None),
            )
        except MissingReportEvidence as exc:
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS,
                {"mensaje": "El informe no dispone de todos los indicadores solicitados.",
                 "requisitos_pendientes": exc.missing},
            )

        settings = deps.settings.reports if deps.settings else None
        directory = Path(settings.directory if settings else "informes")
        ttl = timedelta(hours=settings.ttl_hours if settings else 24)
        logo_path = settings.logo_path if settings else None

        content = await asyncio.to_thread(_render, p.formato, document, ctx.now, logo_path)
        report_id = _uuid()
        path = directory / f"{report_id}.{p.formato}"
        await asyncio.to_thread(_write, path, content)

        safe = re.sub(r"[^\w\- ]+", "", document.title).strip()[:60] or "informe_ejecutivo"
        file_name = f"{safe}.{p.formato}"

        async with deps.db.session() as db:
            db.add(
                Report(
                    id=report_id,
                    user_id=ctx.user.user_id,
                    title=document.title,
                    format=p.formato,
                    file_name=file_name,
                    path=str(path),
                    expires_at=ctx.now + ttl,
                )
            )

        url = f"/api/reports/{report_id}"
        diag_emit(
            EventStage.REPORT_GENERATION,
            data={
                "report_id": report_id, "formato": p.formato, "secciones": len(document.blocks),
                "tool": "generar_informe_ejecutivo",
            },
        )
        return ToolResult(
            ToolStatus.OK,
            {
                "informe": file_name,
                "secciones": len(document.blocks),
                "periodo": f"{lo.isoformat()} a {hi.isoformat()}",
                "ambito": dept_name or "toda la empresa",
                "enlace": url,
                "caduca_en_horas": int(ttl.total_seconds() // 3600),
            },
            {"type": "download", "title": document.title, "format": p.formato, "url": url, "file_name": file_name},
        )

    return Tool(
        "generar_informe_ejecutivo",
        "Genera un informe ejecutivo de RRHH completo para presentar a dirección: KPIs de plantilla, "
        "distribución por departamento y puesto, análisis detallado de absentismo, tendencia mensual, "
        "saldos de vacaciones y trabajo temporal. Admite un periodo personalizado (desde/hasta) para "
        "informes históricos o comparativos (p. ej. los últimos 12 meses). Produce el documento "
        "directamente sin consultas previas. Formatos: PDF (predeterminado), Excel o PowerPoint. "
        "Si la petición es sobre coste salarial, gasto en nóminas o cualquier importe económico, esta "
        "herramienta redirige automáticamente a 'analisis_economico_nominas' y entrega ESE informe "
        "(mejor usar esa herramienta directamente si ya sabes que la petición es económica).",
        InformeEjecutivoParams,
        handler,
        permission=Permission.INFORMES_GENERAR,
        audit_resource="informes",
        timeout_seconds=600,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(generar(deps))
    registry.register(generar_ejecutivo(deps))
