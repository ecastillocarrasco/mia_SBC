"""Fase I — cierre de seguridad del Advanced Reporting Engine.

Auditoría (resultado, no solo afirmado): ninguno de los tres proveedores de identidad de este
sistema (``DevIdentityProvider``, ``EasyAuthIdentityProvider``, ``EntraIdIdentityProvider`` —
``src/mia/auth/providers.py``) expone una forma de preguntar "¿qué permisos tiene AHORA el usuario
X?" sin una petición HTTP real de ese usuario: los tres leen la identidad de la petición en curso
(cabeceras inyectadas por la plataforma, o el token Bearer que manda el cliente), nunca de un
directorio consultable por `user_id` en segundo plano. Existe un cliente de Microsoft Graph con
credenciales de aplicación (``mia.connectors.graph.GraphClient``), pero hoy solo está conectado al
correo (permisos de Graph distintos a los de lectura de asignaciones de rol) y no hay ningún
identificador de Service Principal configurado para consultar *app role assignments* — construir eso
sería añadir infraestructura nueva, no usar la existente, así que no se ha hecho.

Por tanto, siguiendo la instrucción explícita del usuario ("si no existe infraestructura suficiente...
no inventes una solución aparente: documenta la dependencia y conserva el bloqueo seguro"), esta fase
NO añade ninguna fuente de autorización en vivo nueva. En su lugar:

1. La EJECUCIÓN asíncrona de trabajos que exigen un permiso sensible (hoy, solo
   ``informe_economico_nominas``) queda bloqueada por defecto
   (``JobsSettings.allow_sensitive_async = False`` — ``src/mia/settings.py``), tanto en el ejecutor
   (``run_informe_economico_nominas``) como en los dos puntos de ENVÍO (la herramienta conversacional
   ``informe_economico_en_segundo_plano`` y el endpoint REST ``POST /api/jobs/informe-economico``) —
   nunca se encola un trabajo que de todas formas no podría ejecutarse.
2. La DESCARGA (``GET /api/reports/{id}``) vuelve a comprobar el permiso del informe
   (``Report.required_permission``, nueva columna — migración 0009) contra el usuario REALMENTE
   autenticado EN ESE MOMENTO (``UserDep``, la misma fuente ya usada en cualquier otra ruta) — nunca
   el conjunto de roles capturado cuando se generó el informe. Esto cierra el hueco de "revocado
   después de generarse, antes de descargarse" sin ninguna infraestructura nueva: reutiliza
   exactamente el sistema de permisos (``Permission``/``ROLE_PERMISSIONS``/``UserContext.require``)
   que ya usa el resto de la aplicación.

Las pruebas de este fichero cubren los 8 escenarios pedidos explícitamente.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from mia.api.services import Services
from mia.auth import Permission, UserContext
from mia.auth.context import ROLE_PERMISSIONS
from mia.auth.providers import DevIdentityProvider
from mia.data import Report
from mia.main import create_app
from mia.modules.registry import build_registry
from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO, run_informe_economico_nominas
from mia.reporting import job_manager
from mia.reporting.worker import ReportJobWorker
from mia.settings import AuthSettings
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
_TEMP_ROLE = "mia._test_fase_i_security_closure"


async def _seeded_services(tmp_path, *, jobs_overrides: dict | None = None):
    """Mismo escenario sintético de agosto de 2026 (coste de empresa, con cotizaciones SS reales) que
    el resto de Fase I/H — expone `db`/`registry`/`settings` directamente."""
    db = await fresh_database(tmp_path, "fase_i_security.db")
    async with db.session() as s:
        sp_id = 2000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                from mia.data import Payslip  # noqa: PLC0415

                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 2000
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

    from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider  # noqa: PLC0415

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    jobs = {"enabled": True, "allow_sensitive_async": True}
    jobs.update(jobs_overrides or {})
    settings = make_settings(tmp_path, jobs=jobs)
    registry = build_registry(db, settings.data.stale_after_minutes, settings=settings, sharepoint=sp)
    services = SimpleNamespace(db=db, registry=registry, settings=settings)
    return services, sp, db


async def _submit_and_run(services, *, user_id: str, roles: list[str]) -> job_manager.JobSnapshot:
    params = {
        "periodo": "agosto de 2026",
        "departamento": None,
        "concepto": "coste_empresa",
        "incluir_grupos_pequenos": False,
        "incluir_inactivos": False,
        "formato": "pdf",
        "titulo": None,
        "_auth": {"user_id": user_id, "display_name": "Enrique", "roles": roles},
    }
    async with services.db.session() as db:
        job_id = await job_manager.submit(db, user_id=user_id, kind=JOB_KIND_INFORME_ECONOMICO, params=params)
    worker = ReportJobWorker(
        services, {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}, worker_id="sec-closure"
    )
    await worker._run_once()
    async with services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None
    return snapshot


def _with_temp_role(permissions: frozenset[Permission]):
    original = dict(ROLE_PERMISSIONS)
    ROLE_PERMISSIONS[_TEMP_ROLE] = permissions
    return original


def _restore_roles(original: dict) -> None:
    ROLE_PERMISSIONS.clear()
    ROLE_PERMISSIONS.update(original)


# ───────────────────────── 1. Protección temporal: la ejecución asíncrona sensible sigue deshabilitada


async def test_sensitive_async_execution_is_disabled_by_default(tmp_path) -> None:
    """Con la configuración por defecto (`allow_sensitive_async=False`), un trabajo encolado
    DIRECTAMENTE en el Job Manager (sin pasar por los puntos de envío, que también lo bloquean —
    probado aparte) nunca se ejecuta con éxito, sin importar si el permiso del usuario es válido."""
    services, sp, db = await _seeded_services(tmp_path, jobs_overrides={"allow_sensitive_async": False})
    try:
        snapshot = await _submit_and_run(services, user_id="u", roles=["mia.admin"])
        assert snapshot.status == "queued"  # sin reintentos agotados: denegado, nunca completado
        assert snapshot.report_id is None
        assert snapshot.error_message is not None
        assert "permission_denied" in snapshot.error_message.lower()
        assert "asíncrona" in snapshot.error_message or "asíncrona" in snapshot.error_message
    finally:
        await sp.aclose()
        await db.dispose()


async def test_sensitive_async_submission_is_rejected_at_both_entry_points(tmp_path) -> None:
    """Ni la herramienta conversacional ni el endpoint REST deben encolar siquiera el trabajo —
    denegado en el envío, no solo tras encolarlo para fallar después."""
    services, sp, db = await _seeded_services(tmp_path, jobs_overrides={"allow_sensitive_async": False})
    try:
        # Herramienta conversacional: ni siquiera debe estar registrada (ver test dedicado en
        # test_job_manager_economic_integration.py); aquí se confirma que no aparece en ESTE registry.
        assert "informe_economico_en_segundo_plano" not in services.registry._tools

        # Endpoint REST: sigue existiendo (no depende del registro de herramientas), pero debe denegar.
        settings = services.settings
        app_services = Services.build(settings, db=services.db)
        app_services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u"))
        app = create_app(settings, services=app_services)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/jobs/informe-economico",
                    json={"periodo": "agosto de 2026", "concepto": "coste_empresa", "formato": "pdf"},
                )
            assert response.status_code == 403
            # Dentro del mismo `lifespan_context`, antes de que `app_services.aclose()` libere la
            # base de datos compartida con `services.db` al salir de este bloque.
            async with services.db.session() as db_check:
                from mia.data.jobs import ReportJob  # noqa: PLC0415

                rows = (await db_check.scalars(select(ReportJob))).all()
            assert rows == []  # nunca se llegó a encolar nada
    finally:
        await sp.aclose()
        await db.dispose()


# ───────────────────────── 2-4. Revocación antes de la ejecución (con el camino habilitado para
# comprobar la causa de la denegación, no solo que algo se deniega)


async def test_authorized_user_submits_then_permission_is_revoked_before_execution_is_denied(tmp_path) -> None:
    """Pasos 1-4 pedidos: usuario autorizado envía el trabajo (1), se revoca su permiso antes de que
    el worker lo ejecute (2), el worker lo intenta (3), y la ejecución se deniega — nunca se reutiliza
    el permiso ya caducado (4)."""
    services, sp, db = await _seeded_services(tmp_path)  # allow_sensitive_async=True: se prueba la causa real
    try:
        original = _with_temp_role(frozenset({Permission.NOMINAS_IMPORTES, Permission.INFORMES_GENERAR}))
        try:
            params = {
                "periodo": "agosto de 2026",
                "departamento": None,
                "concepto": "coste_empresa",
                "incluir_grupos_pequenos": False,
                "incluir_inactivos": False,
                "formato": "pdf",
                "titulo": None,
                "_auth": {"user_id": "u", "display_name": "Enrique", "roles": [_TEMP_ROLE]},
            }
            async with services.db.session() as db_submit:
                job_id = await job_manager.submit(
                    db_submit, user_id="u", kind=JOB_KIND_INFORME_ECONOMICO, params=params
                )
            # 2. Revocación mientras el trabajo sigue en cola.
            ROLE_PERMISSIONS[_TEMP_ROLE] = frozenset()

            # 3. El worker lo intenta.
            worker = ReportJobWorker(
                services, {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}, worker_id="sec-revoke"
            )
            claimed = await worker._run_once()
            assert claimed is True

            # 4. Se deniega — nunca completado con datos económicos para un permiso ya revocado.
            async with services.db.session() as db_check:
                snapshot = await job_manager.get(db_check, job_id)
            assert snapshot is not None
            assert snapshot.status == "queued"
            assert snapshot.report_id is None
            assert snapshot.error_message is not None and "permission_denied" in snapshot.error_message.lower()
        finally:
            _restore_roles(original)
    finally:
        await sp.aclose()
        await db.dispose()


async def test_permission_change_concurrent_with_the_jobs_own_state_transition_is_still_caught(tmp_path) -> None:
    """Paso 7 pedido: la revocación llega justo al filo del cambio de estado del propio trabajo (justo
    después de que el worker lo reclame, "queued" → "running", no mientras aún esperaba) — sigue sin
    poder ejecutarse con un permiso ya revocado, porque la comprobación es la MISMA en cualquier punto
    de la ejecución (consulta `ROLE_PERMISSIONS` en el momento de llamar a la herramienta real, nunca
    una copia tomada antes)."""
    services, sp, db = await _seeded_services(tmp_path)
    try:
        original = _with_temp_role(frozenset({Permission.NOMINAS_IMPORTES, Permission.INFORMES_GENERAR}))
        try:
            params = {
                "periodo": "agosto de 2026",
                "departamento": None,
                "concepto": "coste_empresa",
                "incluir_grupos_pequenos": False,
                "incluir_inactivos": False,
                "formato": "pdf",
                "titulo": None,
                "_auth": {"user_id": "u", "display_name": "Enrique", "roles": [_TEMP_ROLE]},
            }
            async with services.db.session() as db_submit:
                job_id = await job_manager.submit(
                    db_submit, user_id="u", kind=JOB_KIND_INFORME_ECONOMICO, params=params
                )
            async with services.db.session() as db_claim:
                claimed_job = await job_manager.claim_next(db_claim, worker_id="sec-concurrent")
            assert claimed_job is not None and claimed_job.id == job_id  # ya está "running"

            # El cambio de permiso llega EN ESE PRECISO INSTANTE, con el estado ya en "running".
            ROLE_PERMISSIONS[_TEMP_ROLE] = frozenset()

            from mia.modules.rrhh.informes.jobs import run_informe_economico_nominas as executor  # noqa: PLC0415

            with pytest.raises(RuntimeError, match="permission_denied"):
                await executor(services, claimed_job)
        finally:
            _restore_roles(original)
    finally:
        await sp.aclose()
        await db.dispose()


# ───────────────────────── 5-6. Revocación posterior a la generación, anterior a la descarga


async def test_permission_revoked_after_the_report_exists_but_before_download_is_denied(tmp_path) -> None:
    """Pasos 5-6 pedidos: el informe ya se generó con el permiso vigente en ese momento; el permiso se
    revoca DESPUÉS, antes de que la misma persona lo descargue — la descarga debe denegarse, no basta
    con haber sido el propietario."""
    services, sp, db = await _seeded_services(tmp_path)
    try:
        original = _with_temp_role(frozenset({Permission.NOMINAS_IMPORTES, Permission.INFORMES_GENERAR}))
        try:
            snapshot = await _submit_and_run(services, user_id="u", roles=[_TEMP_ROLE])
            assert snapshot.status == "completed" and snapshot.report_id

            # Revocación DESPUÉS de generarse, ANTES de descargarse.
            ROLE_PERMISSIONS[_TEMP_ROLE] = frozenset()

            app_services = Services.build(services.settings, db=services.db)
            app_services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u", dev_roles=[_TEMP_ROLE]))
            app = create_app(services.settings, services=app_services)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(f"/api/reports/{snapshot.report_id}")
            assert response.status_code == 403
        finally:
            _restore_roles(original)
    finally:
        await sp.aclose()
        await db.dispose()


async def test_permission_intact_at_download_time_still_succeeds(tmp_path) -> None:
    """Control: si el permiso SIGUE vigente en el momento de la descarga, debe seguir funcionando con
    normalidad — la reautorización no debe convertirse en una denegación universal."""
    services, sp, db = await _seeded_services(tmp_path)
    try:
        original = _with_temp_role(frozenset({Permission.NOMINAS_IMPORTES, Permission.INFORMES_GENERAR}))
        try:
            snapshot = await _submit_and_run(services, user_id="u", roles=[_TEMP_ROLE])
            assert snapshot.status == "completed" and snapshot.report_id

            app_services = Services.build(services.settings, db=services.db)
            app_services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u", dev_roles=[_TEMP_ROLE]))
            app = create_app(services.settings, services=app_services)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(f"/api/reports/{snapshot.report_id}")
            assert response.status_code == 200
        finally:
            _restore_roles(original)
    finally:
        await sp.aclose()
        await db.dispose()


async def test_a_report_with_no_required_permission_is_unaffected_by_this_closure(tmp_path) -> None:
    """No se debilita nada que ya funcionaba: un informe que NO exige ningún permiso especial
    (cualquier dominio salvo nóminas) sigue descargándose solo con ser el propietario, exactamente
    igual que antes de este cierre."""
    services, sp, db = await _seeded_services(tmp_path)
    try:
        async with services.db.session() as db_write:
            db_write.add(
                Report(
                    id="rep-sin-permiso",
                    user_id="u",
                    title="Plantilla",
                    format="pdf",
                    file_name="plantilla.pdf",
                    path=str(tmp_path / "plantilla.pdf"),
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                    required_permission=None,
                )
            )
        (tmp_path / "plantilla.pdf").write_bytes(b"%PDF-1.4 contenido de prueba")

        app_services = Services.build(services.settings, db=services.db)
        app_services.identity = DevIdentityProvider(AuthSettings(dev_user_id="u", dev_roles=["mia.responsable"]))
        app = create_app(services.settings, services=app_services)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/reports/rep-sin-permiso")
        assert response.status_code == 200
    finally:
        await sp.aclose()
        await db.dispose()


# ───────────────────────── 8. Fallo de disponibilidad de la fuente de autorizaciones (equivalente:
# el propio valor guardado no se puede verificar) → denegación segura, nunca se trata como "sin
# restricción"


async def test_an_unverifiable_required_permission_denies_safely_rather_than_allowing(tmp_path) -> None:
    """Si `Report.required_permission` contiene un valor que no corresponde a ningún `Permission`
    conocido (dato corrupto, o la fuente de verificación no puede resolverlo por cualquier motivo),
    la descarga debe denegarse — nunca interpretarse como "sin restricción" y servirse igualmente."""
    services, sp, db = await _seeded_services(tmp_path)
    try:
        async with services.db.session() as db_write:
            db_write.add(
                Report(
                    id="rep-permiso-invalido",
                    user_id="u",
                    title="Informe con permiso corrupto",
                    format="pdf",
                    file_name="x.pdf",
                    path=str(tmp_path / "x.pdf"),
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                    required_permission="esto:no_existe_como_permission",
                )
            )
        (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4 contenido de prueba")

        app_services = Services.build(services.settings, db=services.db)
        app_services.identity = DevIdentityProvider(
            AuthSettings(dev_user_id="u")
        )  # mia.admin: todos los permisos reales
        app = create_app(services.settings, services=app_services)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/reports/rep-permiso-invalido")
        assert response.status_code == 403  # ni siquiera mia.admin lo descarga: no se puede verificar
    finally:
        await sp.aclose()
        await db.dispose()
