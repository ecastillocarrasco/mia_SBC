"""Persistencia y respuesta comunes para un ``Document`` ya construido: renderizar, guardar en
disco, registrar en la tabla ``reports`` y devolver el enlace de descarga.

Compartido por cualquier informe que construya su propio ``Document`` directamente (sin pasar por
una tabla/presentación intermedia, a diferencia de ``_build_report_result`` en ``informes.tools``,
que sí parte de una presentación) — antes duplicado entre ``generar_informe_ejecutivo`` y el nuevo
informe comparativo de turnos/fichajes, ahora una sola función."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator

from mia.assets import resolve_logo
from mia.conversation import ToolContext, ToolResult, ToolStatus
from mia.data import Report
from mia.data.models import _uuid
from mia.diagnostics import EventStage
from mia.diagnostics import emit as diag_emit
from mia.modules.rrhh.common import Deps
from mia.reporting.document import Document
from mia.reporting.render import RENDERERS

ReportFormat = Literal["pdf", "xlsx", "pptx", "html", "docx"]


def _as_list(value: Any) -> Any:
    """Un formato suelto ("pdf") se trata como una lista de un elemento — el contrato de toda la
    vida para quien solo pide un formato; varios formatos a la vez se piden como lista."""
    return [value] if isinstance(value, str) else value


ReportFormats = Annotated[list[ReportFormat], BeforeValidator(_as_list)]
"""Tipo de campo Pydantic compartido por los 3 informes que exportan a fichero (``generar_informe``,
``generar_informe_ejecutivo``, ``informe_comparativo_turnos_fichajes``): acepta un formato suelto o
varios a la vez, para generarlos todos en una sola petición en vez de obligar a repetir la llamada
una vez por formato."""


def normalize_formats(formato: str | Sequence[str]) -> list[str]:
    """Sin duplicados, en el orden pedido, validados contra los renderizadores reales — nunca una
    lista arbitraria sin comprobar, aunque el campo Pydantic ya la valide en el caso normal (esta
    función también la usan llamadas internas que no pasan por ese modelo)."""
    raw = [formato] if isinstance(formato, str) else list(formato)
    formats: list[str] = []
    for item in raw:
        if item not in RENDERERS:
            raise ValueError(f"Formato de informe no soportado: {item!r}")
        if item not in formats:
            formats.append(item)
    if not formats:
        raise ValueError("Se necesita al menos un formato de informe")
    return formats


def render_document(formato: str, document: Document, generated: datetime, logo: Path | None) -> bytes:
    return RENDERERS[formato](document, generated, resolve_logo(logo))


_PREVIEW_MAX_TABLES = 2
_PREVIEW_MAX_TABLE_ROWS = 12
_PREVIEW_MAX_CHARTS = 2


def _build_preview(document: Document) -> dict[str, Any] | None:
    """Adelanto ligero del documento para la pantalla (2D/3D) -- nunca el informe entero, que solo
    se entrega como fichero descargable. Genérico a propósito: toma los bloques ``table``/``chart``
    que YA construyó el llamador (cualquier informe que pase por ``persist_document_report``, no
    solo fichajes/turnos) y los recorta, sin derivar nada nuevo. Deja fuera ``kpis``/``annex``: los
    KPIs ya tienen su propio formato compacto (pensado para Holograma) y un anexo es detalle a
    granel, no una vista previa. Devuelve ``None`` cuando el documento no tiene ni tablas ni
    gráficos que mostrar (p. ej. un informe que es solo narrativa), para no añadir una clave vacía."""
    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    for block in document.blocks:
        if block.kind == "table" and len(tables) < _PREVIEW_MAX_TABLES:
            data = block.data or {}
            columns = data.get("columns") or []
            rows = data.get("rows") or []
            if columns and rows:
                tables.append(
                    {
                        "title": block.title,
                        "columns": columns,
                        "rows": rows[:_PREVIEW_MAX_TABLE_ROWS],
                        "total_rows": len(rows),
                        "truncated": len(rows) > _PREVIEW_MAX_TABLE_ROWS,
                    }
                )
        elif block.kind == "chart" and block.data and len(charts) < _PREVIEW_MAX_CHARTS:
            charts.append(dict(block.data))
    if not tables and not charts:
        return None
    return {"tables": tables, "charts": charts}


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def persist_document_report(
    deps: Deps,
    ctx: ToolContext,
    document: Document,
    *,
    formato: str | Sequence[str],
    tool_name: str,
    default_file_stem: str = "informe",
    extra_summary: dict[str, Any] | None = None,
    required_permission: str | None = None,
) -> ToolResult:
    """Renderiza ``document`` en uno o varios formatos, persiste cada uno en disco, lo registra en
    ``reports`` (un registro por formato, cada uno con su propia caducidad) y devuelve el
    ``ToolResult`` de descarga. Con un único formato, la forma de ``summary``/``presentation`` es
    EXACTAMENTE la de siempre (compatibilidad con ``jobs.py`` y el resto de llamadores existentes,
    que leen ``summary["enlace"]``); con varios formatos a la vez se añade ``summary["informes"]`` y
    ``presentation["type"] == "downloads"``, sin alterar la forma del caso de un solo formato."""
    formats = normalize_formats(formato)
    settings = deps.settings.reports if deps.settings else None
    ttl = timedelta(hours=settings.ttl_hours if settings else 24)
    logo_path = settings.logo_path if settings else None
    safe = re.sub(r"[^\w\- ]+", "", document.title).strip()[:60] or default_file_stem

    items: list[dict[str, str]] = []
    for fmt in formats:
        content = await asyncio.to_thread(render_document, fmt, document, ctx.now, logo_path)
        report_id = _uuid()
        path = f"{report_id}.{fmt}"
        storage = deps.services.get("report_storage")
        if storage is None:
            directory = Path(settings.directory if settings else "informes")
            await asyncio.to_thread(_write, directory / path, content)
            path = str(directory / path)
        else:
            await storage.write(path, content)

        file_name = f"{safe}.{fmt}"
        async with deps.db.session() as db:
            db.add(
                Report(
                    id=report_id,
                    user_id=ctx.user.user_id,
                    title=document.title,
                    format=fmt,
                    file_name=file_name,
                    path=str(path),
                    required_permission=required_permission,
                    expires_at=ctx.now + ttl,
                )
            )
        url = f"/api/reports/{report_id}"
        diag_emit(
            EventStage.REPORT_GENERATION,
            data={"report_id": report_id, "formato": fmt, "secciones": len(document.blocks), "tool": tool_name},
        )
        items.append({"formato": fmt, "archivo": file_name, "enlace": url})

    caduca_en_horas = int(ttl.total_seconds() // 3600)
    # El preview es solo para pantalla (2D/3D) -- nunca para el modelo, que ya tiene bastante con
    # "secciones" (un recuento) para confirmar que el informe no salió vacío. Por eso vive
    # únicamente en la presentation, nunca en el summary.
    preview = _build_preview(document)
    if len(items) == 1:
        only = items[0]
        presentation: dict[str, Any] = {
            "type": "download",
            "title": document.title,
            "format": only["formato"],
            "url": only["enlace"],
            "file_name": only["archivo"],
        }
        if preview is not None:
            presentation["preview"] = preview
        return ToolResult(
            ToolStatus.OK,
            {
                "informe": only["archivo"],
                "secciones": len(document.blocks),
                "enlace": only["enlace"],
                "caduca_en_horas": caduca_en_horas,
                **(extra_summary or {}),
            },
            presentation,
        )
    presentation = {
        "type": "downloads",
        "title": document.title,
        "items": [{"url": i["enlace"], "format": i["formato"], "file_name": i["archivo"]} for i in items],
    }
    if preview is not None:
        presentation["preview"] = preview
    return ToolResult(
        ToolStatus.OK,
        {
            "informes": items,
            "secciones": len(document.blocks),
            "caduca_en_horas": caduca_en_horas,
            **(extra_summary or {}),
        },
        presentation,
    )
