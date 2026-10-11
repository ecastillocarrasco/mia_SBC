"""Fase G: worker en segundo plano, genérico por tipo de trabajo (``kind``), que sondea el Job Manager
(``mia.reporting.job_manager``) y ejecuta el trabajo correspondiente sin bloquear el bucle de eventos de
la API — ver el docstring de ``job_manager`` para el diseño de reparto sin duplicar trabajo entre varios
workers y la recuperación de trabajos huérfanos tras un reinicio.

Deliberadamente agnóstico de dominio: no sabe nada de nóminas, turnos ni ningún otro negocio concreto —
solo despacha cada ``kind`` al ejecutor que lo registró (ver ``mia.modules.rrhh.informes.jobs`` para el
primero: informes económicos de nóminas). Mantiene la separación entre infraestructura de informes y
dominios de negocio que exige la arquitectura del proyecto."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from mia.observability import get_logger
from mia.reporting import job_manager
from mia.reporting.job_manager import JobSnapshot

log = get_logger(__name__)

Executor = Callable[[Any, JobSnapshot], Awaitable[str]]
"""``(services, job) -> report_id``. Lanza una excepción en caso de fallo real; el worker decide
reintentar (si quedan intentos) o marcar el trabajo como fallido definitivamente."""


class ReportJobWorker:
    """Un único worker por proceso (el patrón de reparto de ``job_manager.claim_next`` ya soporta varias
    instancias/procesos si en el futuro hiciera falta escalar, sin cambios aquí)."""

    def __init__(
        self,
        services: Any,
        executors: dict[str, Executor],
        *,
        poll_interval_seconds: float = 5.0,
        lease_seconds: int = 300,
        worker_id: str | None = None,
    ) -> None:
        self._services = services
        self._executors = executors
        self._poll_interval = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        async with self._services.db.session() as db:
            reaped = await job_manager.reap_stale_leases(db)
        if reaped:
            log.warning("jobs.reaped_stale_leases", count=reaped, worker_id=self._worker_id)
        while True:
            try:
                claimed = await self._run_once()
            except Exception:  # el bucle del worker nunca debe morir por un fallo de un trabajo
                log.exception("jobs.iteration_failed", worker_id=self._worker_id)
                claimed = False
            if not claimed:
                await asyncio.sleep(self._poll_interval)

    async def _run_once(self) -> bool:
        async with self._services.db.session() as db:
            job = await job_manager.claim_next(
                db, worker_id=self._worker_id, kinds=tuple(self._executors), lease_seconds=self._lease_seconds
            )
        if job is None:
            return False
        await self._execute(job)
        return True

    async def _execute(self, job: JobSnapshot) -> None:
        async with self._services.db.session() as db:
            if await job_manager.check_cancel_requested(db, job.id):
                await job_manager.finalize_cancelled(db, job.id)
                return

        executor = self._executors[job.kind]
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.id))
        try:
            report_id = await executor(self._services, job)
        except Exception as exc:
            log.exception("jobs.execution_failed", job_id=job.id, kind=job.kind, worker_id=self._worker_id)
            async with self._services.db.session() as db:
                await job_manager.fail(db, job.id, error=str(exc)[:500])
            return
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        async with self._services.db.session() as db:
            await job_manager.complete(db, job.id, report_id=report_id)

    async def _heartbeat_loop(self, job_id: str) -> None:
        """Mantiene viva la concesión (lease) de un trabajo que tarda más que ``lease_seconds`` —
        sin esto, ``reap_stale_leases`` lo marcaría erróneamente como abandonado mientras sigue en
        curso. Limitación conocida y deliberada de este primer incremento: NO interrumpe el trabajo a
        mitad de ejecución (la llamada a ``analisis_economico_nominas`` es una única operación atómica
        en el motor analítico ya validado, que esta fase no modifica); la cancelación cooperativa solo
        se comprueba ANTES de empezar a ejecutar (ver ``_execute``)."""
        while True:
            await asyncio.sleep(max(1.0, self._lease_seconds / 3))
            async with self._services.db.session() as db:
                await job_manager.heartbeat(db, job_id, worker_id=self._worker_id, lease_seconds=self._lease_seconds)
