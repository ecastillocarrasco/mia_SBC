"""Fase G: Job Manager real (``mia.reporting.job_manager``), respaldado por la tabla ``report_jobs``
(no en memoria — un "reinicio" se simula aquí simplemente abriendo una sesión nueva sobre la MISMA base
de datos, que es justo la garantía que importa). Cada prueba ejercita UNA de las propiedades pedidas en
la ronda de validación del usuario: persistencia, idempotencia, concurrencia entre workers sin
duplicar trabajo, recuperación tras caída de un worker, progreso real, cancelación cooperativa, y
reintentos controlados antes de fallar definitivamente."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mia.data.jobs import JOB_CANCELLED, JOB_COMPLETED, JOB_FAILED, JOB_QUEUED, JOB_RUNNING, ReportJob
from mia.reporting import job_manager as jm
from tests.dbutil import fresh_database


async def test_submitted_job_is_persisted_and_survives_a_new_session(tmp_path: Path) -> None:
    """ "Reinicio" = abrir una sesión nueva sobre la misma base de datos: el trabajo debe seguir ahí."""
    db = await fresh_database(tmp_path, "jobs_persist.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="informe_economico", params={"periodo": "T3 2026"})
    async with db.session() as s:
        snap = await jm.get(s, job_id)
    assert snap is not None
    assert snap.status == JOB_QUEUED
    assert snap.params == {"periodo": "T3 2026"}


async def test_resubmitting_the_same_idempotency_key_returns_the_existing_job(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_idempotent.db")
    async with db.session() as s:
        first = await jm.submit(
            s, user_id="u1", kind="informe_economico", params={"periodo": "T3"}, idempotency_key="k1"
        )
    async with db.session() as s:
        second = await jm.submit(
            s, user_id="u1", kind="informe_economico", params={"periodo": "T3"}, idempotency_key="k1"
        )
    assert first == second
    async with db.session() as s:
        count = len((await s.execute(ReportJob.__table__.select())).all())
    assert count == 1  # nunca dos filas por el mismo envío repetido


async def test_a_failed_job_with_the_same_idempotency_key_can_be_resubmitted(tmp_path: Path) -> None:
    """La idempotencia evita duplicar un trabajo en curso o ya conseguido — no debe impedir reintentar
    algo que falló definitivamente. La misma clave identifica siempre al mismo trabajo lógico: se
    reutiliza la fila (mismo job_id), reiniciada a QUEUED — no una segunda fila con la misma clave
    (que violaría la restricción de unicidad, y además no sería "la misma idempotencia")."""
    db = await fresh_database(tmp_path, "jobs_idempotent_retry.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={}, idempotency_key="k1", max_attempts=1)
    async with db.session() as s:
        await jm.claim_next(s, worker_id="w1")
        await jm.fail(s, job_id, error="boom")
    async with db.session() as s:
        snap = await jm.get(s, job_id)
    assert snap.status == JOB_FAILED
    async with db.session() as s:
        resubmitted_id = await jm.submit(s, user_id="u1", kind="x", params={}, idempotency_key="k1")
    assert resubmitted_id == job_id
    async with db.session() as s:
        snap = await jm.get(s, resubmitted_id)
    assert snap.status == JOB_QUEUED
    assert snap.attempt_count == 0
    assert snap.error_message is None


async def test_two_workers_claiming_concurrently_never_get_the_same_job(tmp_path: Path) -> None:
    """El núcleo de "prevención de ejecución duplicada entre workers": dos intentos de reclamar el
    mismo trabajo en cola, solo uno debe tener éxito. Cada worker usa su propia sesión/conexión (como
    lo haría un proceso distinto); el segundo ve ya confirmado el cambio del primero antes de intentar
    — lo que importa aquí es que el `UPDATE ... WHERE status='queued'` del segundo afecte a 0 filas,
    no una simulación de paralelismo exacto a nivel de hilo."""
    db = await fresh_database(tmp_path, "jobs_claim_race.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})

    async with db.session() as s1:
        claimed1 = await jm.claim_next(s1, worker_id="worker-A")
    async with db.session() as s2:
        claimed2 = await jm.claim_next(s2, worker_id="worker-B")
    assert claimed1 is not None and claimed1.id == job_id
    assert claimed2 is None  # el segundo worker no encontró nada más que reclamar


async def test_claim_next_ignores_jobs_of_a_different_kind(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_kind_filter.db")
    async with db.session() as s:
        await jm.submit(s, user_id="u1", kind="correo", params={})
    async with db.session() as s:
        claimed = await jm.claim_next(s, worker_id="w1", kinds=("informe_economico",))
    assert claimed is None


async def test_stale_lease_from_a_crashed_worker_is_reclaimable(tmp_path: Path) -> None:
    """Un worker que se cae a mitad de un trabajo deja su lease sin renovar: pasado su vencimiento,
    otro worker debe poder recuperarlo — nunca queda huérfano para siempre."""
    db = await fresh_database(tmp_path, "jobs_stale_lease.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})
    async with db.session() as s:
        await jm.claim_next(s, worker_id="worker-A", lease_seconds=1)
    future = datetime.now(UTC) + timedelta(seconds=5)
    async with db.session() as s:
        reaped = await jm.reap_stale_leases(s, now=future)
    assert reaped == 1
    async with db.session() as s:
        snap = await jm.get(s, job_id)
    assert snap.status == JOB_QUEUED
    async with db.session() as s:
        claimed = await jm.claim_next(s, worker_id="worker-B")
    assert claimed is not None and claimed.id == job_id


async def test_a_fresh_lease_is_not_reaped(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_fresh_lease.db")
    async with db.session() as s:
        await jm.submit(s, user_id="u1", kind="x", params={})
    async with db.session() as s:
        await jm.claim_next(s, worker_id="worker-A", lease_seconds=3600)
    async with db.session() as s:
        reaped = await jm.reap_stale_leases(s)
    assert reaped == 0


async def test_progress_updates_persist_and_are_clamped_to_zero_one(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_progress.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})
        await jm.claim_next(s, worker_id="w1")
        await jm.update_progress(s, job_id, progress=0.4, message="procesando julio")
    async with db.session() as s:
        snap = await jm.get(s, job_id)
    assert snap.progress == 0.4
    assert snap.progress_message == "procesando julio"

    async with db.session() as s:
        await jm.update_progress(s, job_id, progress=5.0)  # fuera de rango: se acota
    async with db.session() as s:
        assert (await jm.get(s, job_id)).progress == 1.0


async def test_completing_a_job_links_the_real_report_id(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_complete.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})
        await jm.claim_next(s, worker_id="w1")
        await jm.complete(s, job_id, report_id="report-123")
    async with db.session() as s:
        snap = await jm.get(s, job_id)
    assert snap.status == JOB_COMPLETED
    assert snap.report_id == "report-123"
    assert snap.progress == 1.0


async def test_failed_job_retries_up_to_the_limit_then_gives_up(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_retry.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={}, max_attempts=2)

    for _ in range(2):
        async with db.session() as s:
            claimed = await jm.claim_next(s, worker_id="w1")
            assert claimed is not None and claimed.status == JOB_RUNNING
            await jm.fail(s, job_id, error="fallo transitorio")
        async with db.session() as s:
            snap = await jm.get(s, job_id)
        if snap.attempt_count < snap.max_attempts:
            assert snap.status == JOB_QUEUED
        else:
            assert snap.status == JOB_FAILED
    async with db.session() as s:
        final = await jm.get(s, job_id)
    assert final.status == JOB_FAILED
    assert final.error_message == "fallo transitorio"


async def test_cancelling_a_queued_job_is_immediate(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_cancel_queued.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})
        cancelled = await jm.request_cancel(s, job_id)
    assert cancelled is True
    async with db.session() as s:
        assert (await jm.get(s, job_id)).status == JOB_CANCELLED


async def test_cancelling_a_running_job_is_cooperative_not_immediate(tmp_path: Path) -> None:
    """Un trabajo EN CURSO no se interrumpe a la fuerza: se marca la señal y el propio ejecutor debe
    comprobarla — ver JobCancelled / check_cancel_requested."""
    db = await fresh_database(tmp_path, "jobs_cancel_running.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})
        await jm.claim_next(s, worker_id="w1")
        await jm.request_cancel(s, job_id)
    async with db.session() as s:
        snap = await jm.get(s, job_id)
    assert snap.status == JOB_RUNNING  # todavía no "cancelado": el ejecutor no ha comprobado la señal
    assert snap.cancel_requested is True

    async with db.session() as s:
        assert await jm.check_cancel_requested(s, job_id) is True
        await jm.finalize_cancelled(s, job_id)
    async with db.session() as s:
        assert (await jm.get(s, job_id)).status == JOB_CANCELLED


async def test_cannot_cancel_an_already_completed_job(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_cancel_completed.db")
    async with db.session() as s:
        job_id = await jm.submit(s, user_id="u1", kind="x", params={})
        await jm.claim_next(s, worker_id="w1")
        await jm.complete(s, job_id, report_id="r1")
    async with db.session() as s:
        cancelled = await jm.request_cancel(s, job_id)
    assert cancelled is False
    async with db.session() as s:
        assert (await jm.get(s, job_id)).status == JOB_COMPLETED  # nunca retrocede desde un estado terminal


async def test_list_for_user_returns_only_that_users_jobs_most_recent_first(tmp_path: Path) -> None:
    """Fase H, "consulta de trabajos anteriores autorizados" y "recuperación tras refrescar la página":
    aislamiento por usuario (nunca se ve un trabajo ajeno) y orden por fecha de creación descendente.
    El `sleep` evita que ambos envíos caigan en el mismo tick de reloj (en Windows, ~15 ms de
    resolución): dos envíos reales de un mismo usuario nunca ocurren con esa cercanía."""
    db = await fresh_database(tmp_path, "jobs_list_for_user.db")
    async with db.session() as s:
        first = await jm.submit(s, user_id="u1", kind="x", params={"periodo": "julio"})
    await asyncio.sleep(0.05)
    async with db.session() as s:
        second = await jm.submit(s, user_id="u1", kind="x", params={"periodo": "agosto"})
        await jm.submit(s, user_id="u2", kind="x", params={"periodo": "ajeno"})
    async with db.session() as s:
        snapshots = await jm.list_for_user(s, user_id="u1")
    assert [snap.id for snap in snapshots] == [second, first]
    assert all(snap.user_id == "u1" for snap in snapshots)


async def test_list_for_user_respects_the_limit(tmp_path: Path) -> None:
    db = await fresh_database(tmp_path, "jobs_list_for_user_limit.db")
    async with db.session() as s:
        for i in range(5):
            await jm.submit(s, user_id="u1", kind="x", params={"periodo": str(i)}, idempotency_key=f"k{i}")
    async with db.session() as s:
        snapshots = await jm.list_for_user(s, user_id="u1", limit=2)
    assert len(snapshots) == 2
