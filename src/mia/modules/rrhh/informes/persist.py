"""Persistencia y respuesta comunes para un ``Document`` ya construido: renderizar, guardar en
disco, registrar en la tabla ``reports`` y devolver el enlace de descarga.

Compartido por cualquier informe que construya su propio ``Document`` directamente (sin pasar por
una tabla/presentación intermedia, a diferencia de ``_build_report_result`` en ``informes.tools``,
que sí parte de una presentación) — antes duplicado entre ``generar_informe_ejecutivo`` y el nuevo
informe comparativo de turnos/fichajes, ahora una sola función."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mia.assets import resolve_logo
from mia.conversation import ToolContext, ToolResult, ToolStatus
from mia.data import Report
from mia.data.models import _uuid
from mia.diagnostics import EventStage
from mia.diagnostics import emit as diag_emit
from mia.modules.rrhh.common import Deps
from mia.reporting.document import Document
from mia.reporting.render import RENDERERS


def render_document(formato: str, document: Document, generated: datetime, logo: Path | None) -> bytes:
    return RENDERERS[formato](document, generated, resolve_logo(logo))


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def persist_document_report(
    deps: Deps,
    ctx: ToolContext,
    document: Document,
    *,
    formato: str,
    tool_name: str,
    default_file_stem: str = "informe",
    extra_summary: dict[str, Any] | None = None,
    required_permission: str | None = None,
) -> ToolResult:
    """Renderiza ``document``, lo persiste en disco, lo registra en ``reports`` y devuelve el
    ``ToolResult`` de descarga — idéntico contrato al que ya usaba ``generar_informe_ejecutivo``."""
    settings = deps.settings.reports if deps.settings else None
    ttl = timedelta(hours=settings.ttl_hours if settings else 24)
    logo_path = settings.logo_path if settings else None

    content = await asyncio.to_thread(render_document, formato, document, ctx.now, logo_path)
    report_id = _uuid()
    path = f"{report_id}.{formato}"
    storage = deps.services.get("report_storage")
    if storage is None:
        directory = Path(settings.directory if settings else "informes")
        await asyncio.to_thread(_write, directory / path, content)
        path = str(directory / path)
    else:
        await storage.write(path, content)

    safe = re.sub(r"[^\w\- ]+", "", document.title).strip()[:60] or default_file_stem
    file_name = f"{safe}.{formato}"

    async with deps.db.session() as db:
        db.add(
            Report(
                id=report_id,
                user_id=ctx.user.user_id,
                title=document.title,
                format=formato,
                file_name=file_name,
                path=str(path),
                required_permission=required_permission,
                expires_at=ctx.now + ttl,
            )
        )

    url = f"/api/reports/{report_id}"
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
            **(extra_summary or {}),
        },
        {"type": "download", "title": document.title, "format": formato, "url": url, "file_name": file_name},
    )
