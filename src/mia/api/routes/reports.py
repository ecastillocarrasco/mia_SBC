from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from mia.api.deps import ServicesDep, UserDep
from mia.data import Report

router = APIRouter(prefix="/api", tags=["informes"])

MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@router.get("/reports/{report_id}")
async def download(report_id: str, services: ServicesDep, user: UserDep) -> FileResponse:
    """Solo quien generó el informe puede descargarlo, y solo mientras no caduque."""
    async with services.db.session() as db:
        report = await db.get(Report, report_id)
    expires = report.expires_at if report else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    exists = report is not None and await asyncio.to_thread(Path(report.path).is_file)
    if report is None or report.user_id != user.user_id or not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Informe no encontrado")
    if expires is not None and expires < datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "El informe ha caducado: pídeselo de nuevo a mIA")
    return FileResponse(report.path, media_type=MEDIA.get(report.format), filename=report.file_name)
