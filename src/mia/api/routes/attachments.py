"""Endpoints para subir y gestionar adjuntos conversacionales."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, status

from mia.api.deps import ServicesDep, UserDep
from mia.attachments.model import AttachmentStatus

router = APIRouter(prefix="/api/adjuntos", tags=["adjuntos"])


def _attachment_response(record: Any) -> dict[str, Any]:
    return {
        "attachment_id": record.attachment_id,
        "filename": record.original_filename,
        "mime_type": record.detected_mime_type or record.mime_type,
        "size_bytes": record.size_bytes,
        "status": record.status.value,
        "content_type": record.content_type.value if record.content_type else None,
        "error": record.error_message or None,
        "processing_duration_ms": record.processing_duration_ms,
        "vision_used": record.vision_used,
        "parser": record.parser_used,
    }


@router.post("/upload")
async def upload_attachment(
    file: UploadFile,
    services: ServicesDep,
    user: UserDep,
) -> dict[str, Any]:
    """Sube un archivo adjunto y lo procesa. Devuelve el attachment_id."""
    if not services.settings.attachments.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La funcionalidad de adjuntos no está activa.")

    svc = services.attachment_service
    if svc is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio de adjuntos no disponible.")

    content = await file.read()
    record = await svc.upload(
        content=content,
        filename=file.filename or "archivo",
        declared_mime=file.content_type or "application/octet-stream",
        user_id=user.user_id,
        session_id=None,
        tenant_id=getattr(user, "tenant_id", "default"),
    )

    if record.status == AttachmentStatus.ERROR:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, record.error_message or "Error al procesar el archivo."
        )

    return _attachment_response(record)


@router.get("/{attachment_id}")
async def get_attachment(
    attachment_id: str,
    services: ServicesDep,
    user: UserDep,
) -> dict[str, Any]:
    if not services.settings.attachments.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Adjuntos no activados.")

    svc = services.attachment_service
    if svc is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio de adjuntos no disponible.")

    record = svc.get_for_user(attachment_id, user.user_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Adjunto no encontrado o expirado.")

    return _attachment_response(record)


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: str,
    services: ServicesDep,
    user: UserDep,
) -> None:
    if not services.settings.attachments.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Adjuntos no activados.")

    svc = services.attachment_service
    if svc is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio de adjuntos no disponible.")

    deleted = await svc.delete(attachment_id, user.user_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Adjunto no encontrado.")
