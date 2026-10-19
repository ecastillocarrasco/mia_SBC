"""Descarga de documentos originales (CV, nómina, documento firmado) con permiso y auditoría.

Sustituye a /curriculums/<id>/documento, /nominas/<id>/documento y
/documentos-firmados/<id>/documento del sistema anterior. El fichero se sirve desde
SharePoint en el momento; mIA no guarda copia.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from mia.api.deps import ServicesDep, UserDep
from mia.auth import Permission
from mia.data import CvDocument, Payslip, SignedDocument
from mia.data.repositories import AuditRepository
from mia.modules.rrhh.content import MAX_BYTES
from mia.modules.rrhh.documentos import is_medical_document_type
from mia.observability import current_request_id

router = APIRouter(prefix="/api/documents", tags=["documentos"])

KINDS: dict[str, tuple[Any, Permission, str]] = {
    "cv": (CvDocument, Permission.CURRICULUMS_LEER, "CVDocs"),
    "nomina": (Payslip, Permission.NOMINAS_IMPORTES, "Nominas"),
    "documento": (SignedDocument, Permission.DOCUMENTOS_CONTENIDO, "DocumentosFirmadosV2"),
}


def _media(content: bytes) -> str:
    if content[:4] == b"%PDF":
        return "application/pdf"
    if content[:2] == b"PK":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "application/octet-stream"


@router.get("/{kind}/{item_id}")
async def download(kind: str, item_id: int, services: ServicesDep, user: UserDep) -> Response:
    if kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tipo de documento desconocido")
    model, permission, library = KINDS[kind]
    if not user.has(permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para abrir este documento")
    if services.sharepoint is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SharePoint no está configurado")
    async with services.db.session() as db:
        record = await db.get(model, item_id)
        if (
            kind == "documento"
            and isinstance(record, SignedDocument)
            and is_medical_document_type(record.doc_type)
            and not user.has(Permission.DOCUMENTOS_CONTENIDO_MEDICO)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para abrir documentos de reconocimiento médico")
        outcome = "ok" if record is not None else "not_found"
        await AuditRepository(db).record(
            user_id=user.user_id,
            action=f"descarga:{kind}",
            resource=kind,
            outcome=outcome,
            request_id=current_request_id(),
            detail={"id": item_id},
        )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
    content = await services.sharepoint.download_item_file(library, item_id, MAX_BYTES)
    name = (getattr(record, "file_name", None) or f"{kind}-{item_id}").replace('"', "")
    return Response(
        content,
        media_type=_media(content),
        headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"},
    )
