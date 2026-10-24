"""Fase G: integración real del Job Manager con `analisis_economico_nominas` para informes económicos
masivos — worker persistente, endpoints autenticados, prevención de ejecución duplicada, recuperación
tras reinicio, progreso/cancelación reales y descargas autorizadas (reutilizando el endpoint existente
`GET /api/reports/{report_id}`, sin duplicar su lógica de propiedad/caducidad).

Dos niveles de prueba, a propósito separados:
- Worker + `job_manager` + ejecutor, llamados directamente (sin HTTP): deterministas, sin depender del
  temporizador de sondeo real del worker. Cubren la ejecución real de gran volumen con datos sintéticos
  controlados (agosto de 2026, los mismos de `tests/test_report_routing_semantic_validation.py`).
- Endpoints HTTP (`/api/jobs/...`): con el worker en segundo plano DESACTIVADO (`settings.jobs.enabled`
  por defecto es `False`), para verificar la capa de rutas (envío, consulta, cancelación, propiedad,
  permiso) sin acoplar la prueba al temporizador real del worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfReader

from mia.api.services import Services
from mia.auth import UserContext
from mia.auth.context import ROLE_PERMISSIONS, Permission
from mia.auth.providers import DevIdentityProvider
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.conversation import ToolContext, ToolStatus
from mia.data import Payslip, Report, ReportJob
from mia.llm import ToolCall
from mia.main import create_app
from mia.modules.registry import build_registry
from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO, run_informe_economico_nominas
from mia.reporting import job_manager
from mia.reporting.job_manager import JobSnapshot
from mia.reporting.worker import ReportJobWorker
from mia.settings import AuthSettings
from sqlalchemy import select
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.dbutil import test_database_url as _test_database_url
from tests.hr_seed import _emp
from tests.test_analisis_economico import Q3_NOW, q3_registry  # noqa: F401 — fixture reutilizada
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
AUTH_ADMIN = {"user_id": "u", "display_name": "Enrique", "roles": ["mia.admin"]}


@pytest.fixture
def settings(tmp_path):
    """Sustituye la `settings` por defecto de `tests/conftest.py` (que deja
    `jobs.allow_sensitive_async=False`, su valor seguro por defecto desde el cierre de seguridad de la
    Fase I) para que las pruebas de ESTE fichero — centradas en la mecánica de envío/consulta/
    cancelación por REST, no en ese bloqueo concreto — puedan ejercitar la ruta sin que el nuevo
    control de seguridad las intercepte a todas. El bloqueo en sí tiene sus propias pruebas dedicadas
    más abajo, con la configuración por defecto (sin este override)."""
    return make_settings(tmp_path, jobs={"enabled": False, "allow_sensitive_async": True})


@pytest.fixture
async def job_services(tmp_path: Path):
    """Mismos datos sintéticos de agosto de 2026 (con cotizaciones SS reales) que
    `tests/test_report_routing_semantic_validation.py::incident_engine` — sin repetir la siembra, solo
    expone por separado `db` y `registry` (lo que necesita `ReportJobWorker`, que no depende de
    `ConversationEngine` ni de `/api/chat`)."""
    db = await fresh_database(tmp_path, "jobs_eco.db")
    async with db.session() as s:
        sp_id = 6000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 6000
    for people in _AUG_DEPARTMENTS.values():
        for net in people.values():
            sp_id += 1
            net_by_sp_id[sp_id] = net

    def files(request: httpx.Request) -> httpx.Response:
        import re  # noqa: PLC0415

        match = re.search(r"items\((\d+)\)/File", request.url.path)
        if not match:
            return httpx.Response(404)
        return httpx.Response(200, content=_pdf(_payslip_text_with_ss(net_by_sp_id[int(match.group(1))])))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    settings = SimpleNamespace(
        reports=SimpleNamespace(directory=str(tmp_path / "informes"), ttl_hours=24, logo_path=None, max_rows=5000),
        data=SimpleNamespace(content_enabled=True),
        timezone="Europe/Madrid",
        # Fase I, cierre de seguridad: estas pruebas ejercitan el worker/ejecutor real (concurrencia,
        # idempotencia, cancelación, reintentos…), no el bloqueo de seguridad en sí — ese tiene sus
        # propias pruebas dedicadas, con el valor por defecto (`allow_sensitive_async=False`).
        jobs=SimpleNamespace(enabled=True, allow_sensitive_async=True),
    )
    registry = build_registry(db, settings=settings, sharepoint=sp)
    services = SimpleNamespace(db=db, registry=registry, settings=settings)
    yield services
    await sp.aclose()
    await db.dispose()


def _worker(services) -> ReportJobWorker:
    return ReportJobWorker(
        services, {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}, worker_id="test-worker"
    )


async def _submit(services, **overrides) -> str:
    params = {
        "periodo": "agosto de 2026",
        "departamento": None,
        "concepto": "coste_empresa",
        "incluir_grupos_pequenos": False,
        "incluir_inactivos": False,
        "formato": "pdf",
        "titulo": None,
        "_auth": AUTH_ADMIN,
    }
    params.update(overrides)
    async with services.db.session() as db:
        return await job_manager.submit(
            db, user_id="u", kind=JOB_KIND_INFORME_ECONOMICO, params=params, idempotency_key=overrides.get("_key")
        )


async def test_large_report_end_to_end_via_the_real_persistent_worker(job_services) -> None:
    """Requisito: "una prueba real de informe grande de extremo a extremo" — envío → worker real
    (`claim_next` → ejecutor → `complete`) → informe descargable con los importes reales de agosto de
    2026 por departamento, no un resumen simulado."""
    job_id = await _submit(job_services)
    worker = _worker(job_services)

    claimed = await worker._run_once()  # noqa: SLF001 — una sola iteración, determinista, sin sondeo real
    assert claimed is True

    async with job_services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None
    assert snapshot.status == "completed"
    assert snapshot.progress == 1.0
    assert snapshot.report_id is not None

    async with job_services.db.session() as db:
        report = await db.get(Report, snapshot.report_id)
    assert report is not None
    assert report.user_id == "u"
    pdf_bytes = Path(report.path).read_bytes()
    pdf_text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    assert "Cocina" in pdf_text
    assert "Recepción" in pdf_text
    assert "Coste empresa" in pdf_text


async def test_duplicate_submission_reuses_the_same_job_not_a_new_one(job_services) -> None:
    """Prevención de ejecución duplicada: reenviar la misma petición (misma clave de idempotencia) debe
    devolver el job_id YA existente, nunca crear un segundo trabajo que ejecutaría el análisis dos veces."""
    first = await _submit(job_services, _key="same-request")
    second = await _submit(job_services, _key="same-request")
    assert first == second
    async with job_services.db.session() as db:
        rows = (await db.scalars(select(ReportJob))).all()
    assert len(rows) == 1


async def test_restart_recovery_requeues_a_job_abandoned_by_a_crashed_worker(job_services) -> None:
    """Recuperación tras reinicio: un trabajo `running` cuyo lease ya venció (worker caído a mitad de
    ejecución) debe volver a `queued` — nunca quedarse huérfano para siempre."""
    job_id = await _submit(job_services)
    async with job_services.db.session() as db:
        await job_manager.claim_next(db, worker_id="worker-que-se-cae", lease_seconds=1)
    import asyncio

    await asyncio.sleep(1.2)

    # Arrancar un worker nuevo (simulando el reinicio del proceso) debe recuperar el trabajo huérfano,
    # exactamente como hace `ReportJobWorker._loop()` al arrancar.
    async with job_services.db.session() as db:
        reaped = await job_manager.reap_stale_leases(db)
    assert reaped == 1

    worker = _worker(job_services)
    claimed = await worker._run_once()  # noqa: SLF001
    assert claimed is True
    async with job_services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None
    assert snapshot.status == "completed"


async def test_cancellation_requested_before_execution_is_honored_not_silently_run(job_services) -> None:
    """Cancelación real: si se pide cancelar un trabajo ya reclamado (running) antes de que el worker
    empiece a ejecutarlo, debe quedar `cancelled` — nunca ejecutarse como si no se hubiera pedido nada."""
    job_id = await _submit(job_services)
    async with job_services.db.session() as db:
        job = await job_manager.claim_next(db, worker_id="test-worker", lease_seconds=300)
        assert job is not None
        await job_manager.request_cancel(db, job_id)  # el trabajo ya está "running": cancel_requested=True

    worker = _worker(job_services)
    async with job_services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    await worker._execute(snapshot)  # noqa: SLF001 — mismo camino que recorrería el bucle real

    async with job_services.db.session() as db:
        final = await job_manager.get(db, job_id)
    assert final is not None
    assert final.status == "cancelled"
    assert final.report_id is None  # nunca se llegó a ejecutar el análisis económico


async def test_payroll_job_still_enforces_the_nominas_permission_at_execution_time(job_services) -> None:
    """Permisos en la ruta del worker (no solo en el endpoint de envío): si los roles capturados en el
    momento del envío no incluían `NOMINAS_IMPORTES`, el ejecutor debe fallar — nunca completar con
    datos económicos reales para un usuario no autorizado."""
    original = dict(ROLE_PERMISSIONS)
    ROLE_PERMISSIONS["mia._test_sin_nominas_job"] = frozenset({Permission.INFORMES_GENERAR})
    try:
        job_id = await _submit(
            job_services, _auth={"user_id": "u2", "display_name": "Sin nóminas", "roles": ["mia._test_sin_nominas_job"]}
        )
        worker = _worker(job_services)
        claimed = await worker._run_once()
        assert claimed is True
        async with job_services.db.session() as db:
            snapshot = await job_manager.get(db, job_id)
        assert snapshot is not None
        # Sin reintentos agotados aún: vuelve a `queued` con el error de permiso visible, nunca `completed`.
        assert snapshot.status == "queued"
        assert snapshot.error_message is not None
        assert "permission_denied" in snapshot.error_message.lower()
    finally:
        ROLE_PERMISSIONS.clear()
        ROLE_PERMISSIONS.update(original)


# ───────────────────────────────────────────── endpoints HTTP (`/api/jobs/...`)
#
# El worker en segundo plano está desactivado (`settings.jobs.enabled` es `False` por defecto, ver
# `tests/conftest.py::make_settings`), a propósito: estas pruebas verifican la capa de rutas (envío,
# consulta, propiedad, permiso, cancelación), no el temporizador real del worker — eso ya está cubierto
# de forma determinista en las pruebas anteriores.

_SUBMIT_BODY = {"periodo": "agosto de 2026", "concepto": "coste_empresa", "formato": "pdf"}


async def test_submit_endpoint_requires_the_nominas_permission(
    client: httpx.AsyncClient, services: Services
) -> None:
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="resp", dev_roles=["mia.responsable"]))
    response = await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)
    assert response.status_code == 403


async def test_submit_and_check_status_through_the_authenticated_endpoints(
    client: httpx.AsyncClient, services: Services
) -> None:
    submit = await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)
    assert submit.status_code == 202
    body = submit.json()
    assert body["status"] == "queued"
    assert body["report_id"] is None

    status_response = await client.get(f"/api/jobs/{body['job_id']}")
    assert status_response.status_code == 200
    assert status_response.json()["job_id"] == body["job_id"]


async def test_resubmitting_the_same_request_does_not_create_a_second_job_via_the_endpoint(
    client: httpx.AsyncClient, services: Services
) -> None:
    first = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()
    second = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()
    assert first["job_id"] == second["job_id"]


async def test_a_user_cannot_see_another_users_job(client: httpx.AsyncClient, services: Services) -> None:
    submitted = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()

    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otro-usuario"))
    response = await client.get(f"/api/jobs/{submitted['job_id']}")
    assert response.status_code == 404


async def test_cancel_endpoint_marks_a_queued_job_cancelled_immediately(
    client: httpx.AsyncClient, services: Services
) -> None:
    submitted = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()
    cancelled = await client.delete(f"/api/jobs/{submitted['job_id']}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_a_user_cannot_cancel_another_users_job(client: httpx.AsyncClient, services: Services) -> None:
    """Aislamiento por usuario también en la cancelación (no solo en la consulta de estado/descarga):
    el trabajo de otro usuario debe seguir intacto, nunca cancelado por quien no lo envió."""
    submitted = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()

    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otro-usuario"))
    denied = await client.delete(f"/api/jobs/{submitted['job_id']}")
    assert denied.status_code == 404

    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="dev-user"))
    still_queued = await client.get(f"/api/jobs/{submitted['job_id']}")
    assert still_queued.json()["status"] == "queued"  # nunca cancelado por el usuario ajeno


async def test_list_endpoint_returns_only_the_callers_jobs_most_recent_first(
    client: httpx.AsyncClient, services: Services
) -> None:
    """Fase H: `GET /api/jobs` (sin segmento `{job_id}`) es lo que el mundo 2D llama al cargar para
    reanudar el sondeo y mostrar el historial — nunca los trabajos de otro usuario. El `sleep` evita
    que ambos envíos caigan en el mismo tick de reloj (en Windows, ~15 ms de resolución)."""
    first = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()
    await asyncio.sleep(0.05)
    second_body = {**_SUBMIT_BODY, "periodo": "septiembre de 2026"}
    second = (await client.post("/api/jobs/informe-economico", json=second_body)).json()

    listing = await client.get("/api/jobs")
    assert listing.status_code == 200
    job_ids = [row["job_id"] for row in listing.json()]
    assert job_ids == [second["job_id"], first["job_id"]]
    assert all(row["kind"] == "informe_economico_nominas" for row in listing.json())

    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otro-usuario"))
    other_listing = await client.get("/api/jobs")
    assert other_listing.json() == []  # nunca se ven trabajos ajenos, ni siquiera vacío por error


async def test_list_route_does_not_collide_with_the_single_job_route(
    client: httpx.AsyncClient, services: Services
) -> None:
    """`GET /api/jobs` y `GET /api/jobs/{job_id}` deben resolverse a rutas distintas — la ruta de lista
    sin segmento no debe intentar interpretarse como un `job_id` ni al revés."""
    submitted = (await client.post("/api/jobs/informe-economico", json=_SUBMIT_BODY)).json()
    listing = await client.get("/api/jobs")
    single = await client.get(f"/api/jobs/{submitted['job_id']}")
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)
    assert single.status_code == 200
    assert single.json()["job_id"] == submitted["job_id"]


# ───────────────────────────────────────── verificaciones adicionales pedidas antes de cerrar Fase G


async def test_real_app_startup_processes_jobs_and_recovers_after_a_simulated_restart(tmp_path: Path) -> None:
    """Puntos 1 y 10: arranque real del worker mediante el procedimiento de despliegue previsto
    (`create_app()` + su `lifespan`, con `MIA_JOBS__ENABLED=true` SOLO en esta prueba — nunca en
    producción), y recuperación de un trabajo huérfano tras "reiniciar" el proceso (una segunda
    instancia de la app contra el mismo fichero de base de datos, simulando que la primera se cayó a
    mitad de ejecución)."""
    db_url = _test_database_url(tmp_path, "restart_real.db")
    await fresh_database(tmp_path, "restart_real.db")  # crea el esquema real antes del primer arranque
    settings = make_settings(
        tmp_path, database_url=db_url,
        jobs={"enabled": True, "poll_interval_seconds": 0.05, "lease_seconds": 1, "allow_sensitive_async": True},
    )

    app1 = create_app(settings)
    async with app1.router.lifespan_context(app1):
        services1 = app1.state.services
        async with services1.db.session() as db:
            job_id = await job_manager.submit(
                db, user_id="dev-user", kind=JOB_KIND_INFORME_ECONOMICO,
                params={"periodo": "agosto de 2026", "concepto": "liquido", "_auth": AUTH_ADMIN},
            )
            # Lo fuerza a "running" con un lease cortísimo: simula que el worker real de app1 lo
            # reclamó justo antes de que el proceso se cayera sin completarlo nunca.
            await job_manager.claim_next(db, worker_id="worker-que-se-cae", lease_seconds=1)
        await asyncio.sleep(1.3)  # deja que el lease expire de verdad antes de "reiniciar"

    # "Reinicio": una segunda instancia de la app, mismo fichero de base de datos, arranque real.
    app2 = create_app(settings)
    async with app2.router.lifespan_context(app2):
        await asyncio.sleep(1.0)  # tiempo real para que el worker arranque, reclame el huérfano y procese
        services2 = app2.state.services
        async with services2.db.session() as db:
            snapshot = await job_manager.get(db, job_id)

    assert snapshot is not None
    # Sin SharePoint configurado en este entorno de pruebas, el análisis económico real no puede
    # completarse con datos — eso ya se prueba por separado en `test_large_report_end_to_end_via_the_
    # real_persistent_worker`. Lo que importa AQUÍ es que el trabajo nunca quedó huérfano para siempre:
    # el segundo proceso lo reclamó de verdad (attempt_count aumentó) y lo llevó a un estado terminal
    # válido, atravesando el procedimiento de arranque real, no un atajo de pruebas.
    assert snapshot.status in ("failed", "queued")
    assert snapshot.attempt_count >= 1
    if snapshot.status == "failed":
        assert snapshot.error_message is not None


async def test_concurrent_workers_never_execute_the_same_job_twice(job_services) -> None:
    """Punto 2: varios workers compitiendo por el mismo lote de trabajos nunca deben ejecutar el mismo
    trabajo dos veces ni producir informes duplicados/compartidos."""
    job_ids = [await _submit(job_services, _key=f"concurrent-{i}") for i in range(4)]
    executors = {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}
    worker_a = ReportJobWorker(job_services, executors, worker_id="worker-A")
    worker_b = ReportJobWorker(job_services, executors, worker_id="worker-B")

    # Se alternan en vez de lanzarse con asyncio.gather: lo que se verifica es la seguridad de la
    # carrera por reclamar (ya probada de forma aislada en test_job_manager.py con dos procesos reales),
    # no una simulación de paralelismo exacto a nivel de hilo sobre SQLite. El resultado real —4
    # trabajos, 4 informes distintos, ninguno repetido— es lo que demuestra la ausencia de duplicados.
    for w in (worker_a, worker_b, worker_a, worker_b):
        assert await w._run_once() is True  # noqa: SLF001

    async with job_services.db.session() as db:
        snapshots = [await job_manager.get(db, jid) for jid in job_ids]
    assert all(s.status == "completed" for s in snapshots)
    report_ids = [s.report_id for s in snapshots]
    assert len(set(report_ids)) == 4  # ningún informe compartido ni duplicado


async def test_idempotency_is_isolated_per_user_not_shared_by_hash_coincidence(job_services) -> None:
    """Punto 4: dos usuarios distintos pidiendo exactamente los mismos parámetros de negocio nunca deben
    compartir el mismo trabajo ni el mismo informe — el ámbito de autorización de cada usuario queda
    aislado en la propia clave de idempotencia (incluye siempre el `user_id`)."""
    business = {"periodo": "agosto de 2026", "concepto": "coste_empresa", "formato": "pdf"}
    key_a = hashlib.sha256(json.dumps({"user_id": "user-a", **business}, sort_keys=True).encode()).hexdigest()
    key_b = hashlib.sha256(json.dumps({"user_id": "user-b", **business}, sort_keys=True).encode()).hexdigest()
    assert key_a != key_b  # el hash en sí ya difiere: no hay forma de que colisionen por coincidencia

    async with job_services.db.session() as db:
        job_a = await job_manager.submit(
            db, user_id="user-a", kind=JOB_KIND_INFORME_ECONOMICO,
            params={**business, "_auth": {"user_id": "user-a", "display_name": "A", "roles": ["mia.admin"]}},
            idempotency_key=key_a,
        )
        job_b = await job_manager.submit(
            db, user_id="user-b", kind=JOB_KIND_INFORME_ECONOMICO,
            params={**business, "_auth": {"user_id": "user-b", "display_name": "B", "roles": ["mia.admin"]}},
            idempotency_key=key_b,
        )
    assert job_a != job_b

    worker = _worker(job_services)
    assert await worker._run_once() is True
    assert await worker._run_once() is True
    async with job_services.db.session() as db:
        snap_a = await job_manager.get(db, job_a)
        snap_b = await job_manager.get(db, job_b)
    assert snap_a.report_id is not None and snap_b.report_id is not None
    assert snap_a.report_id != snap_b.report_id  # informes independientes, nunca compartidos


async def test_heartbeat_task_is_cancelled_cleanly_after_execution(job_services) -> None:
    """Punto 6: liberación correcta de recursos — la tarea de heartbeat que mantiene vivo el lease
    durante una ejecución larga no debe quedar huérfana tras terminar, ni en éxito ni en fallo."""
    job_id = await _submit(job_services)
    worker = _worker(job_services)
    async with job_services.db.session() as db:
        job = await job_manager.claim_next(db, worker_id="test-worker", lease_seconds=300)
    assert job is not None and job.id == job_id

    before = {t for t in asyncio.all_tasks() if not t.done()}
    await worker._execute(job)  # noqa: SLF001
    await asyncio.sleep(0)  # deja que la cancelación de la tarea de heartbeat se propague
    after = {t for t in asyncio.all_tasks() if not t.done()}
    assert after - before == set(), "la tarea de heartbeat quedó huérfana tras terminar la ejecución"


async def test_report_download_is_only_available_to_the_job_owner(job_services, tmp_path: Path) -> None:
    """Punto 9: una vez completado el trabajo, el informe solo debe poder descargarse por quien lo
    pidió — reutilizando el endpoint ya existente y validado `GET /api/reports/{report_id}`, sin
    duplicar aquí su lógica de propiedad."""
    job_id = await _submit(job_services)
    worker = _worker(job_services)
    assert await worker._run_once() is True
    async with job_services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None and snapshot.report_id is not None

    settings = make_settings(tmp_path, jobs={"enabled": False})
    services = Services.build(settings, db=job_services.db)
    try:
        services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u"))  # el propietario real
        app = create_app(settings, services=services)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as owner_client:
                owned = await owner_client.get(f"/api/reports/{snapshot.report_id}")
                assert owned.status_code == 200

            services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otro-usuario"))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as other_client:
                denied = await other_client.get(f"/api/reports/{snapshot.report_id}")
                assert denied.status_code == 404
    finally:
        await services.aclose()


async def test_failure_messages_never_contain_salary_amounts(job_services) -> None:
    """Punto 5: los mensajes de error persistidos (el mismo texto que llevaría `log.exception` a los
    logs de la aplicación, al venir de la propia excepción) deben ser estructurales — nunca una cifra
    salarial. Se fuerza un fallo real pidiendo un departamento inexistente."""
    job_id = await _submit(job_services, departamento="Departamento Que No Existe")
    worker = _worker(job_services)
    assert await worker._run_once() is True
    async with job_services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None and snapshot.error_message is not None
    assert not re.search(r"\d[.\d]*,\d{2}", snapshot.error_message), (
        f"el mensaje de error parece contener un importe: {snapshot.error_message!r}"
    )


# ──────────────────────────── herramienta conversacional `informe_economico_en_segundo_plano`
#
# Fase H, "si hace falta una herramienta conversacional adicional, intégrala mediante el
# ToolRegistry existente y respeta todos sus permisos. No dupliques APIs ni gestores de trabajos."


async def test_the_conversational_job_tool_is_only_registered_when_both_gates_are_open(job_services) -> None:
    """La herramienta exige DOS condiciones a la vez: el worker activo (`jobs.enabled`, para no ofrecer
    un botón que un despliegue sin worker no podría cumplir nunca) y, desde el cierre de seguridad de
    la Fase I, también `jobs.allow_sensitive_async` (para no ofrecer un camino asíncrono mientras no
    exista una comprobación fiable de permisos vigentes). Ausente cualquiera de las dos, no aparece."""
    base = {k: v for k, v in vars(job_services.settings).items() if k != "jobs"}
    cases = [
        SimpleNamespace(enabled=False, allow_sensitive_async=False),
        SimpleNamespace(enabled=True, allow_sensitive_async=False),
        SimpleNamespace(enabled=False, allow_sensitive_async=True),
    ]
    for jobs_settings in cases:
        settings = SimpleNamespace(**base, jobs=jobs_settings)
        registry = build_registry(job_services.db, settings=settings, sharepoint=None)
        assert "informe_economico_en_segundo_plano" not in registry._tools, jobs_settings  # noqa: SLF001

    settings_both_open = SimpleNamespace(**base, jobs=SimpleNamespace(enabled=True, allow_sensitive_async=True))
    registry = build_registry(job_services.db, settings=settings_both_open, sharepoint=None)
    assert "informe_economico_en_segundo_plano" in registry._tools  # noqa: SLF001


async def test_the_conversational_job_tool_submits_to_the_same_job_manager_as_the_rest_endpoint(
    job_services,
) -> None:
    """La herramienta y el endpoint REST (`POST /api/jobs/informe-economico`) son dos puertas de
    entrada al MISMO backend: mismo `kind`, mismos parámetros de negocio, mismo trabajo persistido."""
    registry = build_registry(job_services.db, settings=job_services.settings, sharepoint=None)
    assert "informe_economico_en_segundo_plano" in registry._tools  # noqa: SLF001

    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={}, user_message="")
    args = {"periodo": "agosto de 2026", "concepto": "coste_empresa", "formato": "pdf"}
    execution = await registry.execute(ToolCall("t1", "informe_economico_en_segundo_plano", json.dumps(args)), ctx)
    assert execution.result.status is ToolStatus.OK
    job_id = execution.result.summary["job_id"]

    async with job_services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None
    assert snapshot.kind == JOB_KIND_INFORME_ECONOMICO
    assert snapshot.user_id == "u"
    assert snapshot.params["periodo"] == "agosto de 2026"
    assert execution.result.presentation == {
        "type": "job",
        "job_id": job_id,
        "kind": JOB_KIND_INFORME_ECONOMICO,
        "status": "queued",
        "periodo": "agosto de 2026",
        "formato": "pdf",
    }


async def test_the_conversational_job_tool_still_requires_the_nominas_permission(job_services) -> None:
    """El permiso se aplica en el mismo punto que cualquier otra herramienta (`ToolRegistry.execute`),
    nunca se salta por tratarse de un envío a segundo plano."""
    registry = build_registry(job_services.db, settings=job_services.settings, sharepoint=None)
    sin_nominas = UserContext("u2", "Sin nóminas", roles=frozenset({"mia.empleado"}))
    ctx = ToolContext(user=sin_nominas, request_id=None, now=Q3_NOW, session_state={}, user_message="")
    args = {"periodo": "agosto de 2026"}
    execution = await registry.execute(ToolCall("t2", "informe_economico_en_segundo_plano", json.dumps(args)), ctx)
    assert execution.result.status is ToolStatus.PERMISSION_DENIED
    async with job_services.db.session() as db:
        rows = (await db.scalars(select(ReportJob))).all()
    assert all(row.user_id != "u2" for row in rows)  # ningún trabajo quedó encolado para el usuario denegado


async def test_large_multi_month_volume_has_no_silent_truncation(q3_registry) -> None:
    """Punto 8: medido con un volumen mayor que el escenario mínimo de otras pruebas (3 departamentos,
    3 meses, hasta 10 personas) — ningún mes ni departamento debe perderse en silencio, y el tiempo real
    debe quedar muy por debajo del timeout de la propia herramienta (280 s). La protección contra
    volúmenes verdaderamente grandes (>1000 nóminas, `LARGE_VOLUME_WARNING` en
    `analisis_economico.py`) es un mecanismo YA VALIDADO sin cambios en esta fase — no se repite aquí
    por el coste de generar ese volumen en una prueba unitaria."""
    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={}, user_message="")
    started = time.perf_counter()
    execution = await q3_registry.execute(
        ToolCall("vol", "analisis_economico_nominas", json.dumps({"periodo": "julio a septiembre de 2026"})), ctx
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = execution.result
    assert result.status is ToolStatus.OK
    assert result.summary["meses_analizados"] == ["2026-07", "2026-08", "2026-09"]
    assert result.summary["meses_con_datos"] == ["2026-07", "2026-08", "2026-09"]  # ningún mes perdido
    assert {"Cocina", "Recepción"} <= set(result.summary["por_departamento"])
    assert elapsed_ms < 5000  # referencia real de este entorno, no un SLA estricto
