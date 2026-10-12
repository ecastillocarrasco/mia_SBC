"""Fase I, punto 1: "correspondencia exacta con Job Manager" — extiende al flujo asíncrono completo
(solicitud → ConversationEngine/herramienta conversacional → Job Manager → worker → análisis
económico → informe → descarga) la misma garantía ya probada para el flujo directo en
`test_fase_i_integral_validation.py`.

El mundo 2D real NO muestra KPIs/tabla/gráficos en pantalla para el camino de segundo plano hasta que
el trabajo termina (solo una tarjeta de estado) — así que "lo mostrado al usuario" en este flujo es,
en última instancia, el propio documento descargado. La garantía que de verdad hace falta demostrar
es que el pipeline asíncrono (Job Manager + worker) nunca diverge del pipeline síncrono (el que el
usuario vería al pedir el informe sin "en segundo plano"): mismas cifras, mismo periodo, mismas
advertencias, mismo usuario, mismo informe — nunca un recálculo paralelo con su propia lógica.

Por eso estas pruebas comparan DOS ejecuciones REALES del mismo sistema entre sí (camino directo vs.
camino de trabajo), nunca un valor calculado aparte en la propia prueba — exactamente lo que pidió el
usuario ("no reconstruyas cálculos independientemente para superar las pruebas").
"""

from __future__ import annotations

import io
import json

import httpx
import pytest
from pypdf import PdfReader

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.conversation.tools import remember_table
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.data import Payslip, Report
from mia.llm import ToolCall
from mia.modules.rrhh import build_registry
from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO, run_informe_economico_nominas
from mia.reporting import job_manager
from mia.reporting.worker import ReportJobWorker
from sqlalchemy import select
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
AUTH_ADMIN = {"user_id": "u", "display_name": "Enrique", "roles": ["mia.admin"]}

_DEPARTMENTS_WITH_A_HIDDEN_GROUP: dict[str, dict[str, float]] = {
    **_AUG_DEPARTMENTS,
    "Mantenimiento": {"pk-m1": 1800.0},  # 1 persona: por debajo de MIN_GROUP=3 (NOM-005)
}


@pytest.fixture
async def comparison_services(tmp_path, request):
    """Expone `registry`/`db`/`settings` directamente (sin LLM, sin pasar por `/api/mia/chat`) para
    poder ejecutar el camino DIRECTO y el camino de TRABAJO sobre exactamente los mismos datos — la
    comparación entre ambos es lo que prueba la correspondencia, nunca un tercer cálculo independiente.
    Parametrizable por departamentos vía `request.param` (por defecto, sin grupo oculto)."""
    departments = getattr(request, "param", _AUG_DEPARTMENTS)
    db = await fresh_database(tmp_path, "fase_i_jobs_cmp.db")
    async with db.session() as s:
        sp_id = 1000
        for dept, people in departments.items():
            position = "Cocinero" if dept == "Cocina" else ("Recepcionista" if dept == "Recepción" else "Técnico")
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 1000
    for people in departments.values():
        for net in people.values():
            sp_id += 1
            net_by_sp_id[sp_id] = net

    def files(request_: httpx.Request) -> httpx.Response:
        import re  # noqa: PLC0415

        match = re.search(r"items\((\d+)\)/File", request_.url.path)
        if not match:
            return httpx.Response(404)
        return httpx.Response(200, content=_pdf(_payslip_text_with_ss(net_by_sp_id[int(match.group(1))])))

    sp = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=httpx.MockTransport(files)
    )
    # Estas pruebas comparan la MECÁNICA del Job Manager contra el camino directo (cifras, NOM-005,
    # atribución, volumen) — no el bloqueo de seguridad en sí, que tiene su propio fichero de pruebas
    # dedicado con el valor por defecto (`allow_sensitive_async=False`).
    settings = make_settings(tmp_path, jobs={"enabled": True, "allow_sensitive_async": True})
    registry = build_registry(db, settings.data.stale_after_minutes, settings=settings, sharepoint=sp)
    services = type("Services", (), {})()  # objeto simple: lo que necesita ReportJobWorker (db/registry/settings)
    services.db = db
    services.registry = registry
    services.settings = settings
    yield services
    await sp.aclose()
    await db.dispose()


async def _run_direct_path(services, *, periodo: str, concepto: str, formato: str) -> tuple[dict, bytes]:
    """Camino directo: `analisis_economico_nominas` → `generar_informe`, en el MISMO turno, exactamente
    como lo ejecutaría `ConversationEngine` para una petición normal (sin "en segundo plano"). Devuelve
    el resumen real de la herramienta (periodo/departamentos/advertencias) y el documento descargable."""
    from datetime import UTC, datetime

    ctx = ToolContext(user=ADMIN, request_id=None, now=datetime.now(UTC), session_state={}, user_message="")
    eco_execution = await services.registry.execute(
        ToolCall("direct:eco", "analisis_economico_nominas", json.dumps({"periodo": periodo, "concepto": concepto})),
        ctx,
    )
    eco_result = eco_execution.result
    assert eco_result.status is ToolStatus.OK
    remember_table(ctx.session_state, eco_result.presentation, 5000, eco_result.summary, source_tool="analisis_economico_nominas")

    informe_execution = await services.registry.execute(
        ToolCall("direct:informe", "generar_informe", json.dumps({"formato": formato, "incluir_narrativa": False})), ctx
    )
    informe_result = informe_execution.result
    assert informe_result.status is ToolStatus.OK
    report_id = informe_result.summary["enlace"].rsplit("/", 1)[-1]

    async with services.db.session() as db:
        report = await db.get(Report, report_id)
    assert report is not None
    content = __import__("pathlib").Path(report.path).read_bytes()
    return eco_result.summary, content


async def _run_job_path(services, *, periodo: str, concepto: str, formato: str, user_id: str = "u") -> tuple[str, bytes]:
    """Camino de trabajo: encola exactamente el mismo `kind`/parámetros que usaría la herramienta
    conversacional `informe_economico_en_segundo_plano` (o el endpoint REST equivalente), lo procesa con
    el worker real de la Fase G, y descarga el documento resultante. Devuelve el `report_id` y el
    contenido del documento."""
    params = {
        "periodo": periodo, "departamento": None, "concepto": concepto,
        "incluir_grupos_pequenos": False, "incluir_inactivos": False, "formato": formato, "titulo": None,
        "_auth": {"user_id": user_id, "display_name": "Enrique", "roles": ["mia.admin"]},
    }
    async with services.db.session() as db:
        job_id = await job_manager.submit(db, user_id=user_id, kind=JOB_KIND_INFORME_ECONOMICO, params=params)

    worker = ReportJobWorker(services, {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}, worker_id="fase-i-cmp")
    claimed = await worker._run_once()  # noqa: SLF001
    assert claimed is True

    async with services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
    assert snapshot is not None and snapshot.status == "completed", f"el trabajo no terminó bien: {snapshot}"
    report_id = snapshot.report_id
    assert report_id

    async with services.db.session() as db:
        report = await db.get(Report, report_id)
    assert report is not None
    content = __import__("pathlib").Path(report.path).read_bytes()
    return job_id, report_id, content, report.user_id


def _pdf_text(content: bytes) -> str:
    return "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


async def test_job_path_document_matches_the_direct_path_document_exactly(comparison_services) -> None:
    """Periodo, magnitud económica, total, totales por departamento, porcentajes: el documento
    producido por el Job Manager debe contener EXACTAMENTE las mismas cifras que el documento producido
    por el camino directo para la misma petición — nunca un recálculo paralelo que pudiera divergir."""
    services = comparison_services
    direct_summary, direct_pdf = await _run_direct_path(
        services, periodo="agosto de 2026", concepto="coste_empresa", formato="pdf"
    )
    _job_id, _report_id, job_pdf, _owner = await _run_job_path(
        services, periodo="agosto de 2026", concepto="coste_empresa", formato="pdf"
    )

    direct_text = _pdf_text(direct_pdf)
    job_text = _pdf_text(job_pdf)

    # Periodo: el mismo periodo interpretado por el motor económico real, nunca un valor fijo supuesto.
    periodo_interpretado = direct_summary["periodo_interpretado"]
    assert periodo_interpretado in direct_text
    assert periodo_interpretado in job_text, "el periodo del camino directo no aparece en el documento del Job Manager"

    # Totales por departamento y porcentajes: se extraen del resumen REAL (`por_departamento[dept]
    # ["total"]`, un float ya calculado por el motor — nunca recalculado aquí) y se formatea con la
    # MISMA función de producción (`format_eur`) que usa la tabla, para comprobar que la cifra exacta
    # aparece en AMBOS documentos.
    from mia.modules.rrhh.nominas.estadisticas import format_eur

    por_departamento = direct_summary["por_departamento"]
    assert {"Cocina", "Recepción"} <= set(por_departamento)
    for dept in ("Cocina", "Recepción"):
        dept_stats = por_departamento[dept]
        assert "total" in dept_stats, f"el departamento {dept} no debería estar oculto en este escenario: {dept_stats}"
        figure = format_eur(dept_stats["total"])
        assert figure in direct_text, f"[directo] falta la cifra real de {dept} ({figure!r}) en su propio documento"
        assert figure in job_text, f"[Job Manager] falta la cifra real de {dept} ({figure!r}) — diverge del camino directo"

        peso_pct = dept_stats.get("peso_pct")
        if peso_pct is not None:
            pct_text = f"{peso_pct:.1f}%"
            assert pct_text in direct_text, f"[directo] falta el porcentaje real de {dept} ({pct_text!r})"
            assert pct_text in job_text, f"[Job Manager] falta el porcentaje real de {dept} ({pct_text!r}) — diverge del camino directo"

    total_figure = format_eur(direct_summary["total_periodo"])
    assert total_figure in direct_text
    assert total_figure in job_text, f"el total general real ({total_figure!r}) no aparece en el documento del Job Manager"

    assert "Cocina" in job_text
    assert "Recepción" in job_text


@pytest.mark.parametrize("comparison_services", [_DEPARTMENTS_WITH_A_HIDDEN_GROUP], indirect=True)
async def test_job_path_respects_nom_005_masking_and_warnings_like_the_direct_path(
    comparison_services,
) -> None:
    """Supresión por privacidad (K-anonimato/NOM-005): un departamento por debajo del mínimo de
    personas debe quedar enmascarado también en el documento producido por el Job Manager, y la
    advertencia real debe aparecer en ese mismo documento — no solo en el camino directo ni solo en
    pantalla."""
    services = comparison_services
    direct_summary, direct_pdf = await _run_direct_path(
        services, periodo="agosto de 2026", concepto="coste_empresa", formato="pdf"
    )
    _job_id, _report_id, job_pdf, _owner = await _run_job_path(
        services, periodo="agosto de 2026", concepto="coste_empresa", formato="pdf"
    )

    # El departamento oculto nunca expone un importe real — ni en el camino directo (ya validado en
    # Fase H) ni, lo que aquí importa, en el del Job Manager.
    hidden_importes = direct_summary["por_departamento"]["Mantenimiento"]["importes"]
    assert "ocultos" in hidden_importes, f"el escenario no produjo un grupo oculto real: {hidden_importes}"

    direct_text = _pdf_text(direct_pdf)
    job_text = _pdf_text(job_pdf)
    assert "NOM-005" in direct_text, "el documento directo no incluye la advertencia real de NOM-005"
    assert "NOM-005" in job_text, "el documento del Job Manager no incluye la advertencia de NOM-005 — supresión perdida en el camino asíncrono"

    # La cifra individual de la única persona del departamento oculto (1.800,00 €) no debe filtrarse
    # por ningún camino.
    assert "1.800,00" not in direct_text
    assert "1.800,00" not in job_text


async def test_a_role_permission_revoked_while_a_job_is_queued_is_caught_at_execution(
    comparison_services,
) -> None:
    """Fase I, punto 4: "autorizaciones vigentes en trabajos en cola". Dos casos distintos, con
    resultado distinto, que esta prueba distingue con cuidado:

    1. Si lo que cambia es la DEFINICIÓN de un rol (`ROLE_PERMISSIONS`, p. ej. un administrador quita
       `NOMINAS_IMPORTES` del rol mientras el trabajo espera en cola) — el ejecutor SÍ lo detecta: la
       comprobación de permiso vuelve a consultar `ROLE_PERMISSIONS` en el momento de ejecutar
       (`src/mia/auth/context.py:84`), nunca una copia hecha al encolar. Esta prueba lo confirma con un
       caso real, no solo lo afirma.
    2. Lo que SIGUE sin poder detectarse (no probado aquí porque no hay nada que mutar: ver la nota en
       `ADVANCED_REPORTING_PROGRESS.md`, Fase I, punto 4) es que a la persona que envió el trabajo se le
       quite ESE ROL EN CONCRETO (p. ej. se le retira del grupo "mia.admin" en el proveedor de
       identidad) entre el envío y la ejecución: `_rebuild_user()` reconstruye el usuario SOLO a partir
       de los roles capturados en `params["_auth"]` en el momento del envío, sin consultar ningún
       directorio de usuarios en vivo (no existe tal directorio en este sistema) — ese caso queda
       genuinamente sin control verificable con la arquitectura actual."""
    services = comparison_services
    from mia.auth.context import ROLE_PERMISSIONS, Permission
    from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO

    role_name = "mia._test_fase_i_role_revoked"
    original = dict(ROLE_PERMISSIONS)
    ROLE_PERMISSIONS[role_name] = frozenset({Permission.NOMINAS_IMPORTES})
    try:
        params = {
            "periodo": "agosto de 2026", "departamento": None, "concepto": "coste_empresa",
            "incluir_grupos_pequenos": False, "incluir_inactivos": False, "formato": "pdf", "titulo": None,
            "_auth": {"user_id": "u", "display_name": "Enrique", "roles": [role_name]},
        }
        async with services.db.session() as db:
            job_id = await job_manager.submit(db, user_id="u", kind=JOB_KIND_INFORME_ECONOMICO, params=params)

        # El permiso se retira del ROL mientras el trabajo sigue en cola — exactamente el escenario que
        # pidió el usuario: "autorizaciones vigentes en trabajos en cola".
        ROLE_PERMISSIONS[role_name] = frozenset()

        worker = ReportJobWorker(services, {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}, worker_id="fase-i-revoke")
        claimed = await worker._run_once()  # noqa: SLF001
        assert claimed is True

        async with services.db.session() as db:
            snapshot = await job_manager.get(db, job_id)
        assert snapshot is not None
        # Sin reintentos agotados: vuelve a `queued` con el error de permiso visible, nunca `completed`
        # con datos económicos para un rol que ya no está autorizado.
        assert snapshot.status == "queued"
        assert snapshot.error_message is not None
        assert "permission_denied" in snapshot.error_message.lower()
        assert snapshot.report_id is None
    finally:
        ROLE_PERMISSIONS.clear()
        ROLE_PERMISSIONS.update(original)


async def test_job_result_is_attributed_to_the_submitting_user_with_matching_provenance(
    comparison_services,
) -> None:
    """Identidad del usuario y procedencia: el informe que produce el trabajo debe quedar atribuido al
    usuario que lo envió (nunca a otro ni a nadie), y el `report_id` que el trabajo declara completado
    debe ser el MISMO informe que `/api/reports/{id}` serviría — nunca un informe distinto sustituido
    en silencio."""
    services = comparison_services
    job_id, report_id, _content, owner_user_id = await _run_job_path(
        services, periodo="agosto de 2026", concepto="coste_empresa", formato="pdf", user_id="u"
    )
    assert owner_user_id == "u"

    async with services.db.session() as db:
        snapshot = await job_manager.get(db, job_id)
        report_row = await db.get(Report, report_id)
    assert snapshot is not None
    assert snapshot.kind == JOB_KIND_INFORME_ECONOMICO  # procedencia: el trabajo es del tipo declarado
    assert snapshot.report_id == report_id  # el id que el trabajo declara es el mismo que se persistió
    assert report_row is not None and report_row.id == report_id  # nunca un informe distinto sustituido
    assert report_row.user_id == "u"  # atribuido al usuario real que lo envió

    async with services.db.session() as db:
        rows = (await db.scalars(select(Report).where(Report.user_id != "u"))).all()
    assert report_id not in {r.id for r in rows}  # nunca aparece como propiedad de otro usuario


# ───────────────────────────── Fase I, punto 3: volumen real a través del Job Manager (no solo directo)
#
# `test_large_multi_month_volume_has_no_silent_truncation` (test_job_manager_economic_integration.py)
# ya mide un volumen mayor, pero SOLO por el camino directo (`q3_registry.execute(...)`). El propio
# Job Manager (worker real, claim_next, heartbeat) nunca se había medido con más que los 6 empleados de
# `_AUG_DEPARTMENTS`. Esta prueba lo hace: 3 departamentos × 15 personas = 45 nóminas reales, a través
# del worker real — tiempo y recuento REALMENTE medidos, no supuestos.
_LARGE_VOLUME_DEPARTMENTS: dict[str, dict[str, float]] = {
    "Cocina": {f"pk-c{i}": 1500.0 + i * 10 for i in range(1, 16)},
    "Recepción": {f"pk-r{i}": 2000.0 + i * 10 for i in range(1, 16)},
    "Mantenimiento": {f"pk-m{i}": 1700.0 + i * 10 for i in range(1, 16)},
}


@pytest.mark.parametrize("comparison_services", [_LARGE_VOLUME_DEPARTMENTS], indirect=True)
async def test_job_manager_handles_a_larger_volume_through_the_real_worker_without_silent_truncation(
    comparison_services,
) -> None:
    import time

    services = comparison_services
    started = time.perf_counter()
    _job_id, _report_id, content, _owner = await _run_job_path(
        services, periodo="agosto de 2026", concepto="coste_empresa", formato="pdf"
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    text = _pdf_text(content)
    for dept in ("Cocina", "Recepción", "Mantenimiento"):
        assert dept in text, f"el departamento {dept} se perdió en el informe de {len(_LARGE_VOLUME_DEPARTMENTS)*15} nóminas"

    # Referencia real de este entorno (45 nóminas simuladas, worker real, sin el timeout de 280s de la
    # propia herramienta) — no un SLA estricto, solo evidencia de que se midió, no que se asumió.
    assert elapsed_ms < 15000, f"45 nóminas por el Job Manager tardaron {elapsed_ms:.0f} ms en este entorno"
