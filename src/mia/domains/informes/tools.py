"""Informes PDF/Excel a partir del último resultado en tabla de la conversación."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from mia.auth import Permission
from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.conversation.tools import LAST_TABLE
from mia.data import Report
from mia.data.models import _uuid
from mia.domains.common import Deps
from mia.domains.informes.render import to_pdf, to_xlsx


class InformeParams(BaseModel):
    formato: Literal["pdf", "xlsx"] = Field(description="pdf o xlsx (Excel)")
    titulo: str | None = Field(default=None, description="Título (por defecto, el de la tabla)")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def generar(deps: Deps) -> Tool:
    async def handler(p: InformeParams, ctx: ToolContext) -> ToolResult:
        table_data = ctx.session_state.get(LAST_TABLE)
        if not table_data:
            return ToolResult(
                ToolStatus.NOT_FOUND, "No hay ningún resultado en tabla reciente para convertir en informe."
            )
        settings = deps.settings.reports if deps.settings else None
        directory = Path(settings.directory if settings else "informes")
        ttl = timedelta(hours=settings.ttl_hours if settings else 24)
        title = p.titulo or table_data["title"]
        render = to_pdf if p.formato == "pdf" else to_xlsx
        content = render(title, table_data["columns"], table_data["rows"], ctx.now)
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
                "filas": len(table_data["rows"]),
                "enlace": url,
                "caduca_en_horas": int(ttl.total_seconds() // 3600),
            },
            {"type": "download", "title": title, "format": p.formato, "url": url, "file_name": file_name},
        )

    return Tool(
        "generar_informe",
        "Genera un PDF o un Excel con el último resultado en tabla de la conversación y devuelve el enlace.",
        InformeParams,
        handler,
        permission=Permission.INFORMES_GENERAR,
        audit_resource="informes",
    )


def register(registry: ToolRegistry, deps: Deps) -> None:
    registry.register(generar(deps))
