from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response

from mia.api.deps import ServicesDep, UserDep
from mia.auth import Permission, PermissionDeniedError
from mia.data import Report
from mia.diagnostics import EventStage
from mia.diagnostics import emit as diag_emit

router = APIRouter(prefix="/api", tags=["informes"])

MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
}


@router.get("/reports/{report_id}")
async def download(report_id: str, services: ServicesDep, user: UserDep) -> Response:
    """Solo quien generó el informe puede descargarlo, y solo mientras no caduque.

    Fase I (cierre de seguridad): para informes que exigen un permiso sensible
    (``report.required_permission`` — hoy, solo los de ``analisis_economico_nominas``), se vuelve a
    comprobar ese permiso AQUÍ, con el usuario realmente autenticado en ESTA petición (``UserDep``) —
    nunca con el conjunto de roles que tuviera cuando se generó el informe. Cierra el hueco de que un
    permiso revocado después de generarse (pero antes de descargarse) siguiera permitiendo la
    descarga: la comprobación de propiedad por sí sola nunca re-evalúa el permiso del dominio."""
    async with services.db.session() as db:
        report = await db.get(Report, report_id)
    expires = report.expires_at if report else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    legacy_path = Path(report.path) if report is not None and Path(report.path).is_absolute() else None
    exists = False
    if report is not None:
        if legacy_path is not None:
            exists = await asyncio.to_thread(legacy_path.is_file)
        elif services.report_storage is not None:
            exists = await services.report_storage.exists(report.path)
    if report is None or report.user_id != user.user_id or not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Informe no encontrado")
    if expires is not None and expires < datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "El informe ha caducado: pídeselo de nuevo a mIA")
    if report.required_permission:
        try:
            user.require(Permission(report.required_permission))
        except (ValueError, PermissionDeniedError) as exc:
            # ValueError: el valor guardado no corresponde a ningún Permission conocido — denegación
            # segura también ante ese caso, nunca se interpreta como "sin restricción".
            diag_emit(
                EventStage.AUTH_CONTEXT,
                status="error",
                data={"report_id": report_id, "required_permission": report.required_permission, "decision": "denied"},
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Ya no tienes el permiso necesario para este informe"
            ) from exc
    if legacy_path is not None:
        return FileResponse(legacy_path, media_type=MEDIA.get(report.format), filename=report.file_name)
    if services.report_storage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Informe no encontrado")
    content = await services.report_storage.read(report.path)
    return Response(
        content,
        media_type=MEDIA.get(report.format),
        headers={"Content-Disposition": f'attachment; filename="{report.file_name}"'},
    )
