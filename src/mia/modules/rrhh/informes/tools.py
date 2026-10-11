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
from mia.conversation.tools import LAST_TABLE
from mia.data import Report
from mia.data.models import _uuid
from mia.diagnostics import EventStage
from mia.diagnostics import emit as diag_emit
from mia.modules.rrhh.common import Deps, department_problem, resolve_department
from mia.modules.rrhh.informes.document import Document, to_document
from mia.modules.rrhh.informes.render import RENDERERS
from mia.reporting.narrative_generation import generate_narrative_block
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
        narrative = await generate_narrative_block(
            deps.llm, title=title, backend_summary=presentation.get("__summary__") or {}
        )
        if narrative is not None:
            document.blocks.append(narrative)
    logo_path = settings.logo_path if settings else None
    content = await asyncio.to_thread(_render, formato, document, ctx.now, logo_path)
    report_id = _uuid()
    path = directory / f"{report_id}.{formato}"
    await asyncio.to_thread(_write, path, content)
    safe = re.sub(r"[^\w\- ]+", "", title).strip()[:60] or "informe"
    file_name = f"{safe}.{formato}"
    async with deps.db.session() as db:
        db.add(
            Report(
                id=report_id,
                user_id=ctx.user.user_id,
                title=title,
                format=formato,
                file_name=file_name,
                path=str(path),
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


def generar(deps: Deps) -> Tool:
    async def handler(p: InformeParams, ctx: ToolContext) -> ToolResult:
        presentation = ctx.session_state.get(LAST_TABLE)
        if not presentation:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                "No hay ningún resultado reciente (tabla, panel o ficha) para el informe.",
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
        "Genera un PDF, Excel o PowerPoint (plantilla corporativa) con el último resultado de la "
        "conversación: una tabla, el panel de RRHH, una ficha 360, una búsqueda de candidatos… "
        "y devuelve el enlace. Úsalo para «dame un Excel de los candidatos encontrados» o "
        "«exporta esta tabla a PDF».",
        InformeParams,
        handler,
        permission=Permission.INFORMES_GENERAR,
        audit_resource="informes",
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
    return await _build_report_result(
        deps,
        ctx,
        eco_result.presentation,
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
            if payroll_names:
                return await _redirect_to_economic_analysis(deps, ctx, p, lo, hi, _infer_concepto(payroll_names))

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
        timeout_seconds=90,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(generar(deps))
    registry.register(generar_ejecutivo(deps))
