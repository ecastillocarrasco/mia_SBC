"""Job Manager real (Bloque II, Fase G): persistencia, identificadores únicos, idempotencia, estados
recuperables, progreso real, cancelación, reintentos controlados, control de concurrencia entre
workers, y recuperación tras reinicios — sin Celery, Redis ni ningún servicio externo nuevo (decisión
ya tomada en la Fase A de este bloque: en proceso, respaldado por una tabla real,
``mia.data.ReportJob``).

Patrón de reparto entre varios workers sin duplicar trabajo (sección 4, "prevención de ejecución
duplicada entre workers"): un worker candidato a ejecutar un trabajo intenta un ``UPDATE ... WHERE
status='queued'`` sobre ESE id concreto; si otro worker ya lo reclamó entre el SELECT y el UPDATE, la
fila ya no cumple la condición y el ``UPDATE`` afecta a 0 filas — se detecta por ``rowcount`` y se
prueba el siguiente candidato. Es portátil entre SQLite (pruebas) y PostgreSQL (producción): no depende
de ``SELECT ... FOR UPDATE`` ni de ``RETURNING``, que no se comportan igual en ambos.

Un ``lease`` (``lease_owner``/``lease_until``) es lo que permite detectar un worker caído: un trabajo
``running`` cuyo ``lease_until`` ya pasó se considera abandonado y puede reclamarse de nuevo
(``reap_stale_leases``) — así una reinicio del proceso no deja trabajos huérfanos en ``running`` para
siempre (sección 4, "recuperación tras reinicios").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data.jobs import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_VALIDATING,
    ReportJob,
)
from mia.data.models import _now, _uuid

DEFAULT_LEASE_SECONDS = 300


class JobCancelled(Exception):
    """Señal cooperativa: el ejecutor la lanza cuando detecta cancel_requested a mitad de trabajo."""


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """Vista de solo lectura de un ``ReportJob`` (evita pasar el objeto ORM fuera de su sesión)."""

    id: str
    user_id: str
    kind: str
    params: dict[str, Any]
    status: str
    progress: float
    progress_message: str | None
    report_id: str | None
    error_message: str | None
    attempt_count: int
    max_attempts: int
    cancel_requested: bool

    @classmethod
    def from_row(cls, row: ReportJob) -> JobSnapshot:
        return cls(
            id=row.id, user_id=row.user_id, kind=row.kind, params=json.loads(row.params_json),
            status=row.status, progress=row.progress, progress_message=row.progress_message,
            report_id=row.report_id, error_message=row.error_message,
            attempt_count=row.attempt_count, max_attempts=row.max_attempts,
            cancel_requested=row.cancel_requested,
        )


async def submit(
    db: AsyncSession, *, user_id: str, kind: str, params: dict[str, Any],
    idempotency_key: str | None = None, max_attempts: int = 3,
) -> str:
    """Encola un trabajo nuevo. Si ``idempotency_key`` ya existe y su trabajo no ha fallado
    definitivamente, devuelve el ``job_id`` YA existente en vez de duplicar el envío (sección 4:
    "idempotencia") — reenviar la misma petición dos veces (p. ej. por un reintento de red del
    cliente) no debe generar dos informes."""
    if idempotency_key:
        existing = (
            await db.execute(select(ReportJob).where(ReportJob.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status != JOB_FAILED:
                return existing.id
            # El trabajo anterior con esta clave falló definitivamente: se reintenta REUTILIZANDO la
            # misma fila (mismo job_id), no creando una nueva — la columna es única a propósito, y es
            # además la semántica correcta de "idempotencia": la misma clave identifica siempre al
            # mismo trabajo lógico, no una serie de trabajos distintos.
            existing.status = JOB_QUEUED
            existing.params_json = json.dumps(params, ensure_ascii=False)
            existing.kind = kind
            existing.attempt_count = 0
            existing.max_attempts = max_attempts
            existing.error_message = None
            existing.lease_owner = None
            existing.lease_until = None
            existing.progress = 0.0
            existing.progress_message = None
            existing.finished_at = None
            await db.flush()
            return existing.id
    job = ReportJob(
        id=_uuid(), user_id=user_id, kind=kind, params_json=json.dumps(params, ensure_ascii=False),
        idempotency_key=idempotency_key, status=JOB_QUEUED, max_attempts=max_attempts,
    )
    db.add(job)
    await db.flush()
    return job.id


async def get(db: AsyncSession, job_id: str) -> JobSnapshot | None:
    row = await db.get(ReportJob, job_id)
    return JobSnapshot.from_row(row) if row else None


async def claim_next(
    db: AsyncSession, *, worker_id: str, kinds: tuple[str, ...] | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS
) -> JobSnapshot | None:
    """Reclama el siguiente trabajo en cola (el más antiguo primero), o ``None`` si no hay ninguno
    disponible para este worker en este momento. Reintenta con el siguiente candidato si pierde la
    carrera por reclamar uno (ver docstring del módulo)."""
    stmt = select(ReportJob.id).where(ReportJob.status == JOB_QUEUED).order_by(ReportJob.created_at)
    if kinds:
        stmt = stmt.where(ReportJob.kind.in_(kinds))
    candidate_ids = [row[0] for row in (await db.execute(stmt)).all()]
    now = _now()
    for candidate_id in candidate_ids:
        result = await db.execute(
            update(ReportJob)
            .where(ReportJob.id == candidate_id, ReportJob.status == JOB_QUEUED)
            .values(
                status=JOB_RUNNING, lease_owner=worker_id, lease_until=now + timedelta(seconds=lease_seconds),
                started_at=now, attempt_count=ReportJob.attempt_count + 1,
            )
        )
        if result.rowcount == 1:
            await db.flush()
            return await get(db, candidate_id)
    return None


async def heartbeat(db: AsyncSession, job_id: str, *, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
    """Prolonga el lease de un trabajo largo que sigue vivo. Devuelve False si el lease ya se perdió
    (otro worker lo reclamó entre medias) — señal de que el ejecutor actual debe abandonar."""
    result = await db.execute(
        update(ReportJob)
        .where(ReportJob.id == job_id, ReportJob.lease_owner == worker_id, ReportJob.status == JOB_RUNNING)
        .values(lease_until=_now() + timedelta(seconds=lease_seconds))
    )
    await db.flush()
    return result.rowcount == 1


async def update_progress(db: AsyncSession, job_id: str, *, progress: float, message: str | None = None) -> None:
    row = await db.get(ReportJob, job_id)
    if row is None or row.status not in (JOB_RUNNING, JOB_VALIDATING):
        return
    row.progress = max(0.0, min(1.0, progress))
    if message is not None:
        row.progress_message = message
    await db.flush()


async def mark_validating(db: AsyncSession, job_id: str) -> None:
    row = await db.get(ReportJob, job_id)
    if row is not None and row.status == JOB_RUNNING:
        row.status = JOB_VALIDATING
        await db.flush()


async def complete(db: AsyncSession, job_id: str, *, report_id: str) -> None:
    row = await db.get(ReportJob, job_id)
    if row is None:
        return
    row.status = JOB_COMPLETED
    row.report_id = report_id
    row.progress = 1.0
    row.finished_at = _now()
    await db.flush()


async def fail(db: AsyncSession, job_id: str, *, error: str) -> None:
    """Si quedan reintentos, vuelve a QUEUED (sección 4: "reintentos controlados"); si no, FAILED con
    el error visible — nunca un resultado incompleto disfrazado de completado."""
    row = await db.get(ReportJob, job_id)
    if row is None:
        return
    row.error_message = error
    if row.attempt_count < row.max_attempts:
        row.status = JOB_QUEUED
        row.lease_owner = None
        row.lease_until = None
    else:
        row.status = JOB_FAILED
        row.finished_at = _now()
    await db.flush()


async def request_cancel(db: AsyncSession, job_id: str) -> bool:
    """Si el trabajo todavía está en cola, se cancela al instante. Si ya está en curso, se marca
    ``cancel_requested`` para que el ejecutor lo compruebe cooperativamente (ver ``JobCancelled``)."""
    row = await db.get(ReportJob, job_id)
    if row is None or row.status in (JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED):
        return False
    if row.status == JOB_QUEUED:
        row.status = JOB_CANCELLED
        row.finished_at = _now()
    else:
        row.cancel_requested = True
    await db.flush()
    return True


async def finalize_cancelled(db: AsyncSession, job_id: str) -> None:
    row = await db.get(ReportJob, job_id)
    if row is not None and row.status not in (JOB_COMPLETED, JOB_FAILED):
        row.status = JOB_CANCELLED
        row.finished_at = _now()
        await db.flush()


async def check_cancel_requested(db: AsyncSession, job_id: str) -> bool:
    row = await db.get(ReportJob, job_id)
    return bool(row and row.cancel_requested)


async def reap_stale_leases(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Devuelve a QUEUED cualquier trabajo ``running`` cuyo lease ya venció (worker caído o reiniciado
    sin avisar) — sección 4: "recuperación tras reinicios". Se llama al arrancar el proceso, y
    periódicamente mientras corre."""
    ref = now or datetime.now(UTC)
    result = await db.execute(
        update(ReportJob)
        .where(ReportJob.status == JOB_RUNNING, ReportJob.lease_until < ref)
        .values(status=JOB_QUEUED, lease_owner=None, lease_until=None)
    )
    await db.flush()
    return result.rowcount
