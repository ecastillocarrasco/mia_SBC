"""Informes PDF/Excel a partir del último resultado en tabla de la conversación,
y generación autónoma del informe ejecutivo de RRHH para dirección."""

from __future__ import annotations

import asyncio
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
from mia.modules.rrhh.common import Deps, department_problem, resolve_department
from mia.modules.rrhh.informes.document import Document, to_document
from mia.modules.rrhh.informes.render import RENDERERS


class InformeParams(BaseModel):
    formato: Literal["pdf", "xlsx", "pptx"] = Field(description="pdf, xlsx (Excel) o pptx (PowerPoint)")
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


def _render(fmt: str, document: Document, generated: datetime, logo: Path | None) -> bytes:
    return RENDERERS[fmt](document, generated, resolve_logo(logo))


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def generar(deps: Deps) -> Tool:
    async def handler(p: InformeParams, ctx: ToolContext) -> ToolResult:
        presentation = ctx.session_state.get(LAST_TABLE)
        if not presentation:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                "No hay ningún resultado reciente (tabla, panel o ficha) para el informe.",
            )
        settings = deps.settings.reports if deps.settings else None
        directory = Path(settings.directory if settings else "informes")
        ttl = timedelta(hours=settings.ttl_hours if settings else 24)
        document = to_document(presentation, include_detail=p.incluir_detalle, include_chart=p.incluir_grafico)
        if p.titulo:
            document.title = p.titulo
        title = document.title
        logo_path = settings.logo_path if settings else None
        content = await asyncio.to_thread(_render, p.formato, document, ctx.now, logo_path)
        report_id = _uuid()
        path = directory / f"{report_id}.{p.formato}"
        await asyncio.to_thread(_write, path, content)
        safe = re.sub(r"[^\w\- ]+", "", title).strip()[:60] or "informe"
        file_name = f"{safe}.{p.formato}"
        async with deps.db.session() as db:
            db.add(
                Report(
                    id=report_id,
                    user_id=ctx.user.user_id,
                    title=title,
                    format=p.formato,
                    file_name=file_name,
                    path=str(path),
                    expires_at=ctx.now + ttl,
                )
            )
        url = f"/api/reports/{report_id}"
        return ToolResult(
            ToolStatus.OK,
            {
                "informe": file_name,
                "secciones": len(document.blocks),
                "enlace": url,
                "caduca_en_horas": int(ttl.total_seconds() // 3600),
            },
            {"type": "download", "title": title, "format": p.formato, "url": url, "file_name": file_name},
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
    formato: Literal["pdf", "xlsx", "pptx"] = Field(
        default="pdf",
        description="Formato del documento: pdf (predeterminado), xlsx o pptx",
    )
    titulo: str | None = Field(default=None, description="Título personalizado del informe")


def generar_ejecutivo(deps: Deps) -> Tool:
    async def handler(p: InformeEjecutivoParams, ctx: ToolContext) -> ToolResult:
        from mia.modules.rrhh.informes.executive import build_executive_report  # noqa: PLC0415

        today = ctx.now.date()
        lo = p.desde or today.replace(day=1)
        hi = p.hasta or today

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
        "directamente sin consultas previas. Formatos: PDF (predeterminado), Excel o PowerPoint.",
        InformeEjecutivoParams,
        handler,
        permission=Permission.INFORMES_GENERAR,
        audit_resource="informes",
        timeout_seconds=90,
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(generar(deps))
    registry.register(generar_ejecutivo(deps))
