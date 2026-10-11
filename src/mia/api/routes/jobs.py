"""Fase G: endpoints para enviar, consultar y cancelar trabajos en segundo plano de informes
económicos de nóminas. La descarga del informe ya generado reutiliza el endpoint existente
``GET /api/reports/{report_id}`` (``mia.api.routes.reports``) — no se duplica esa lógica de propiedad y
caducidad aquí."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from mia.api.deps import ServicesDep, UserDep, require
from mia.auth import Permission, UserContext
from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO
from mia.reporting import job_manager
from mia.reporting.job_manager import JobSnapshot

router = APIRouter(prefix="/api/jobs", tags=["informes"])

NominasDep = Annotated[UserContext, Depends(require(Permission.NOMINAS_IMPORTES))]


class SubmitInformeEconomicoParams(BaseModel):
    periodo: str = Field(description="Expresión temporal: 'T3 2026', 'agosto 2026', 'últimos 6 meses'…")
    departamento: str | None = Field(default=None, description="Limitar a un departamento; vacío = todos")
    concepto: Literal["liquido", "devengado", "coste_empresa"] = "liquido"
    incluir_grupos_pequenos: bool = False
    incluir_inactivos: bool = False
    formato: Literal["pdf", "xlsx", "pptx", "html"] = "pdf"
    titulo: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: float
    progress_message: str | None
    report_id: str | None
    error_message: str | None


def _to_response(snapshot: JobSnapshot) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=snapshot.id,
        status=snapshot.status,
        progress=snapshot.progress,
        progress_message=snapshot.progress_message,
        report_id=snapshot.report_id,
        error_message=snapshot.error_message,
    )


@router.post("/informe-economico", status_code=status.HTTP_202_ACCEPTED)
async def submit_informe_economico(
    body: SubmitInformeEconomicoParams, services: ServicesDep, user: NominasDep
) -> JobStatusResponse:
    """Encola el análisis económico de nóminas + su renderizado como trabajo en segundo plano —
    pensado para periodos/volúmenes grandes que no caben cómodamente en un turno de conversación."""
    params = body.model_dump()
    params["_auth"] = {"user_id": user.user_id, "display_name": user.display_name, "roles": sorted(user.roles)}
    # Clave de idempotencia determinista (mismo usuario + misma petición de negocio): reenviar la misma
    # solicitud (doble clic, reintento de red) reutiliza el mismo trabajo en vez de duplicarlo.
    business_params = {k: v for k, v in params.items() if k != "_auth"}
    idempotency_key = hashlib.sha256(
        json.dumps({"user_id": user.user_id, **business_params}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    async with services.db.session() as db:
        job_id = await job_manager.submit(
            db, user_id=user.user_id, kind=JOB_KIND_INFORME_ECONOMICO, params=params, idempotency_key=idempotency_key
        )
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None  # noqa: S101 — se acaba de crear/recuperar en la misma transacción
    return _to_response(snapshot)


@router.get("/{job_id}")
async def get_job(job_id: str, services: ServicesDep, user: UserDep) -> JobStatusResponse:
    async with services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    if snapshot is None or snapshot.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trabajo no encontrado")
    return _to_response(snapshot)


@router.delete("/{job_id}")
async def cancel_job(job_id: str, services: ServicesDep, user: UserDep) -> JobStatusResponse:
    """Si el trabajo sigue en cola, se cancela al instante. Si ya está en curso, queda marcado para que
    el worker lo compruebe antes de empezar a ejecutar (ver limitación conocida en
    ``mia.reporting.worker.ReportJobWorker``: no interrumpe un trabajo ya iniciado a mitad de ejecución)."""
    async with services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
        if snapshot is None or snapshot.user_id != user.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trabajo no encontrado")
        await job_manager.request_cancel(db, job_id)
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None  # noqa: S101
    return _to_response(snapshot)
