"""Fase H del Bloque II: integración de la experiencia 2D real (`frontend/src/worlds/2D/mia-2d.js`,
servida por `frontend/mia-2d.html`, que llama a `/api/mia/chat` — NO al contrato moderno
`/api/chat`/`presentations` directamente, ver investigación previa a esta fase).

Caso de aceptación obligatorio (literal del usuario): la misma solicitud de comparativa de costes
salariales de agosto de 2026 que antes producía el PDF equivocado (sección 15) debe ahora, en el mundo
2D, llegar con periodo, métricas (KPIs), gráficos y tabla correctos en el contrato que `mia-2d.js`
consume (`response.data.table/.cards/.charts/.alertas_calidad`) — construido por
`mia.api.legacy_view.legacy_view()` a partir de las MISMAS presentaciones reales que ya usa el resto
del sistema, nunca un camino paralelo.

Encontrada y corregida en esta fase (ver `src/mia/api/legacy_view.py`): los KPI y gráficos de primera
clase que `analisis_economico_nominas` ya calculaba se perdían por completo en la traducción al 2D
(`table_view()` solo traducía columnas/filas), y las advertencias de k-anonimato (clave `advertencias`)
nunca llegaban porque `summary_view()` solo reconocía `alertas_calidad`.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pytest
from pypdf import PdfReader

from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.data import Payslip
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.main import create_app
from mia.modules.rrhh.informes.jobs import JOB_KIND_INFORME_ECONOMICO, run_informe_economico_nominas
from mia.reporting import job_manager
from mia.reporting.worker import ReportJobWorker
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, seed
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss

INCIDENT_REQUEST = (
    "Genera un informe completo de comparativa de costes en nóminas por departamento en agosto de 2026"
)


@pytest.fixture
async def chat_app(tmp_path):
    """Misma construcción que usa `Services.build()` en producción, con datos sintéticos reales de
    agosto de 2026 (con cotizaciones SS, igual que la prueba de la sección 15/16) y un LLM simulado que
    reproduce la petición exacta de la incidencia a través del punto de entrada REAL del 2D
    (`/api/mia/chat`, no `/api/chat`)."""
    db = await fresh_database(tmp_path, "fase_h_2d.db")
    async with db.session() as s:
        sp_id = 7000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 7000
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

    def scripted(req):
        if req.messages[-1].role == "tool":
            return final_answer("Aquí tienes la comparativa de costes por departamento.", "Listo.")
        return tool_call("analisis_economico_nominas", {"periodo": "agosto de 2026", "concepto": "coste_empresa"})

    llm = FakeLLMProvider(scripted)
    settings = make_settings(tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / 'fase_h_2d.db'}")

    from mia.api.services import Services
    from mia.conversation import ConversationEngine, Persona
    from mia.modules.rrhh import build_registry

    services = Services.build(settings, llm=llm, db=db)
    # Services.build() ya construyó su propio registro/engine con sharepoint=None (Deps es inmutable,
    # cerrado en el momento del registro) — se reconstruyen con el SharePoint simulado, exactamente con
    # la misma llamada que hace Services.build() internamente, nunca un camino paralelo.
    registry = build_registry(
        db,
        settings.data.stale_after_minutes,
        settings=settings,
        llm=llm,
        sharepoint=sp,
        enabled=settings.domains.enabled,
    )
    services.registry = registry
    services.sharepoint = sp
    services.engine = ConversationEngine(
        llm=llm,
        tools=registry,
        db=db,
        persona=Persona(),
        timezone=settings.timezone,
        history_turns=settings.history_turns,
        max_tool_rounds=settings.llm.max_tool_rounds,
        turn_budget_seconds=settings.llm.turn_budget_seconds,
        max_output_tokens=settings.llm.max_output_tokens,
    )
    app = create_app(settings, services=services)
    yield app
    await sp.aclose()
    await db.dispose()


async def test_cost_comparison_request_reaches_the_2d_screen_with_period_kpis_charts_and_table(
    chat_app,
) -> None:
    async with chat_app.router.lifespan_context(chat_app):
        transport = httpx.ASGITransport(app=chat_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/mia/chat", json={"message": INCIDENT_REQUEST})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    data = body["data"]

    # Periodo: agosto 2026, nunca octubre (el mes en curso) — ver sección 15.
    table = data["table"]
    assert any("Agosto" in str(col.get("label", "")) or "2026-08" in str(col.get("key", "")) for col in table["columns"]) or "Agosto" in table["title"]
    row_labels = [r.get("Departamento") for r in table["rows"]]
    assert {"Cocina", "Recepción"} <= set(row_labels)

    # KPIs de primera clase (antes se perdían por completo).
    assert data["cards"], "los KPI de analisis_economico_nominas no llegaron a data.cards"
    assert any("gasto" in c["label"].lower() or "total" in c["label"].lower() for c in data["cards"])

    # Gráficos de primera clase (donut/bar ya calculados, nunca un derivado genérico).
    assert data["charts"], "los gráficos de analisis_economico_nominas no llegaron a data.charts"
    assert data["charts"][0]["type"] in ("donut", "bar", "line")
    assert {"Cocina", "Recepción"} & set(data["charts"][0]["labels"])

    # Las presentaciones RAW también viajan en la respuesta (consumidas por el contrato moderno si se
    # necesitara, y evidencia de que no hay un camino paralelo: es la MISMA presentación).
    assert body["presentations"]
    assert body["presentations"][0]["type"] == "table"


# ───────────────────────────── punto 4 del checklist: advertencias de privacidad/cobertura en pantalla

_DEPARTMENTS_WITH_A_HIDDEN_GROUP: dict[str, dict[str, float]] = {
    **_AUG_DEPARTMENTS,
    "Mantenimiento": {"pk-m1": 1800.0},  # 1 persona: por debajo de MIN_GROUP=3 (NOM-005)
}


@pytest.fixture
async def chat_app_with_hidden_department(tmp_path):
    """Mismo escenario que `chat_app`, con un departamento adicional de una sola persona: debe quedar
    oculto por NOM-005, y la advertencia correspondiente debe llegar a `data.alertas_calidad` — el
    punto 7 del checklist de Fase H ("advertencias de privacidad y cobertura")."""
    db = await fresh_database(tmp_path, "fase_h_2d_hidden.db")
    async with db.session() as s:
        sp_id = 7500
        for dept, people in _DEPARTMENTS_WITH_A_HIDDEN_GROUP.items():
            position = "Cocinero" if dept == "Cocina" else ("Recepcionista" if dept == "Recepción" else "Técnico")
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 7500
    for people in _DEPARTMENTS_WITH_A_HIDDEN_GROUP.values():
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

    def scripted(req):
        if req.messages[-1].role == "tool":
            return final_answer("Aquí tienes la comparativa de costes por departamento.", "Listo.")
        return tool_call("analisis_economico_nominas", {"periodo": "agosto de 2026", "concepto": "coste_empresa"})

    llm = FakeLLMProvider(scripted)
    settings = make_settings(tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / 'fase_h_2d_hidden.db'}")

    from mia.api.services import Services
    from mia.conversation import ConversationEngine, Persona
    from mia.modules.rrhh import build_registry

    services = Services.build(settings, llm=llm, db=db)
    registry = build_registry(
        db, settings.data.stale_after_minutes, settings=settings, llm=llm, sharepoint=sp, enabled=settings.domains.enabled
    )
    services.registry = registry
    services.sharepoint = sp
    services.engine = ConversationEngine(
        llm=llm, tools=registry, db=db, persona=Persona(), timezone=settings.timezone,
        history_turns=settings.history_turns, max_tool_rounds=settings.llm.max_tool_rounds,
        turn_budget_seconds=settings.llm.turn_budget_seconds, max_output_tokens=settings.llm.max_output_tokens,
    )
    app = create_app(settings, services=services)
    yield app
    await sp.aclose()
    await db.dispose()


async def test_hidden_department_privacy_warning_reaches_the_2d_screen(chat_app_with_hidden_department) -> None:
    """Punto 7: la advertencia de NOM-005 (grupo oculto por no alcanzar el mínimo de personas) debe
    llegar a `data.alertas_calidad` — no solo quedarse dentro del PDF/XLSX generado."""
    async with chat_app_with_hidden_department.router.lifespan_context(chat_app_with_hidden_department):
        transport = httpx.ASGITransport(app=chat_app_with_hidden_department)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/mia/chat", json={"message": INCIDENT_REQUEST})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("alertas_calidad"), "la advertencia NOM-005 de grupo oculto no llegó a la pantalla"
    assert any("NOM-005" in a for a in data["alertas_calidad"])
    # El departamento de una sola persona aparece listado (para que se sepa que existe), pero sus
    # importes quedan enmascarados — nunca desglosados — y el total general queda marcado como
    # "autorizado" (solo grupos visibles), igual que en el backend ya validado.
    rows_by_dept = {r.get("Departamento"): r for r in data["table"]["rows"]}
    hidden_row = rows_by_dept["Mantenimiento"]
    assert hidden_row["Total"] == "—"
    assert "autorizado" in rows_by_dept["TOTAL (autorizado)"]["Departamento"].lower()


# ───────────────────────────── punto 1 y 3 del checklist: Job Manager real desde el chat del mundo 2D


@pytest.fixture
async def chat_app_jobs_enabled(tmp_path):
    """Mismo escenario sintético de agosto de 2026 que `chat_app`, pero con el worker en segundo plano
    HABILITADO (`settings.jobs.enabled=True`) para que `informe_economico_en_segundo_plano` quede
    registrada en el `ToolRegistry` y el LLM simulado pueda invocarla — exactamente como ocurriría si
    el usuario pidiera el informe "en segundo plano" desde el mundo 2D real."""
    db = await fresh_database(tmp_path, "fase_h_2d_jobs.db")
    async with db.session() as s:
        sp_id = 7800
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 7800
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

    def scripted(req):
        if req.messages[-1].role == "tool":
            return final_answer(
                "He encolado el análisis en segundo plano. Te aviso cuando esté listo.", "Encolado."
            )
        return tool_call(
            "informe_economico_en_segundo_plano",
            {"periodo": "agosto de 2026", "concepto": "coste_empresa", "formato": "pdf"},
        )

    llm = FakeLLMProvider(scripted)
    settings = make_settings(
        tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / 'fase_h_2d_jobs.db'}",
        jobs={"enabled": True, "allow_sensitive_async": True},
    )

    from mia.api.services import Services
    from mia.conversation import ConversationEngine, Persona
    from mia.modules.rrhh import build_registry

    services = Services.build(settings, llm=llm, db=db)
    registry = build_registry(
        db, settings.data.stale_after_minutes, settings=settings, llm=llm, sharepoint=sp, enabled=settings.domains.enabled
    )
    services.registry = registry
    services.sharepoint = sp
    services.engine = ConversationEngine(
        llm=llm, tools=registry, db=db, persona=Persona(), timezone=settings.timezone,
        history_turns=settings.history_turns, max_tool_rounds=settings.llm.max_tool_rounds,
        turn_budget_seconds=settings.llm.turn_budget_seconds, max_output_tokens=settings.llm.max_output_tokens,
    )
    app = create_app(settings, services=services)
    yield app, services
    await sp.aclose()
    await db.dispose()


async def test_background_job_request_is_queued_tracked_and_downloadable_from_the_2d_world(
    chat_app_jobs_enabled,
) -> None:
    """Punto 1 y 3 del checklist: pedir el informe "en segundo plano" desde el chat del 2D real debe
    encolar un trabajo de verdad en el MISMO Job Manager de la Fase G (`data.job`), consultable por
    `GET /api/jobs/{job_id}` y `GET /api/jobs` (historial/recuperación), y el informe completado debe
    poder descargarse por el mismo endpoint ya validado `GET /api/reports/{report_id}` — coherente con
    lo que el usuario vería en pantalla (mismo periodo, mismos departamentos)."""
    app, services = chat_app_jobs_enabled
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/mia/chat",
                json={"message": "Genera en segundo plano el informe económico de nóminas de agosto de 2026"},
            )
            assert response.status_code == 200
            data = response.json()["data"]
            job = data.get("job")
            assert job and job.get("job_id"), "la petición en segundo plano no produjo una tarjeta de trabajo"
            assert job["status"] == "queued"
            assert job["periodo"] == "agosto de 2026"
            job_id = job["job_id"]

            # Punto 1: "consulta de estado mediante polling controlado" — el 2D consultaría exactamente
            # este endpoint antes de que el worker lo procese.
            pending = await client.get(f"/api/jobs/{job_id}")
            assert pending.status_code == 200
            assert pending.json()["status"] == "queued"

            # Ejecuta el trabajo con el MISMO worker/ejecutor ya validado en la Fase G (sin arrancar el
            # bucle real del worker en este test, igual que test_job_manager_economic_integration.py).
            worker = ReportJobWorker(
                services, {JOB_KIND_INFORME_ECONOMICO: run_informe_economico_nominas}, worker_id="fase-h-test-worker"
            )
            claimed = await worker._run_once()  # noqa: SLF001
            assert claimed is True

            # Punto 1: "recuperación de trabajos tras refrescar la página" — una consulta nueva (como la
            # que haría el 2D al cargar) debe ver el trabajo ya completado, con su informe.
            completed = await client.get(f"/api/jobs/{job_id}")
            assert completed.status_code == 200
            completed_body = completed.json()
            assert completed_body["status"] == "completed"
            report_id = completed_body["report_id"]
            assert report_id

            history = await client.get("/api/jobs")
            assert history.status_code == 200
            assert any(row["job_id"] == job_id for row in history.json())

            # Punto 9: descarga autorizada, reutilizando el endpoint ya existente.
            download = await client.get(f"/api/reports/{report_id}")
            assert download.status_code == 200

    # Punto 10: coherencia entre lo mostrado en pantalla y el documento final descargado.
    pdf_text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(download.content)).pages)
    assert "Cocina" in pdf_text
    assert "Recepción" in pdf_text


# ───────────────────────────── punto 4 del checklist: Turnos, Vacaciones y Plantilla desde el 2D real
#
# Reutiliza `client`/`services`/`script` de `tests/conftest.py` (el mismo cliente HTTP que ya ejercita
# `/api/chat` en `tests/test_fase_f_integration.py` para estos tres dominios) apuntando en su lugar a
# `/api/mia/chat` — el punto de entrada real del mundo 2D — para confirmar que la traducción a
# `data.table` funciona igual para Turnos/Vacaciones/Plantilla, no solo para nóminas.


async def test_shift_domain_reaches_the_2d_screen_as_a_table(client: Any, services: Any, script: list) -> None:
    await seed(services.db)

    def scripted(req):
        from mia.llm.fake import final_answer  # noqa: PLC0415

        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("ausencias", {"nombre": "Eva Sol", "desde": "2026-08-03", "hasta": "2026-08-06"})
        return final_answer("Aquí tienes sus ausencias de esa semana.", "Listo.")

    script[0] = scripted
    response = await client.post(
        "/api/mia/chat", json={"message": "Ausencias de Eva Sol la primera semana de agosto"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"].get("table"), "el resultado de ausencias no llegó como tabla al mundo 2D"


async def test_vacation_domain_reaches_the_2d_screen_as_a_table(client: Any, services: Any, script: list) -> None:
    await seed(services.db)

    def scripted(req):
        from mia.llm.fake import final_answer  # noqa: PLC0415

        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("vacaciones", {"desde": "2026-08-01", "hasta": "2026-08-31"})
        return final_answer("Aquí tienes las vacaciones de agosto.", "Listo.")

    script[0] = scripted
    response = await client.post("/api/mia/chat", json={"message": "Vacaciones de agosto de 2026"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"].get("table"), "el resultado de vacaciones no llegó como tabla al mundo 2D"


async def test_employee_roster_domain_reaches_the_2d_screen_as_a_table(
    client: Any, services: Any, script: list
) -> None:
    await seed(services.db)

    def scripted(req):
        from mia.llm.fake import final_answer  # noqa: PLC0415

        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("plantilla", {})
        return final_answer("Aquí tienes la plantilla actual.", "Listo.")

    script[0] = scripted
    response = await client.post("/api/mia/chat", json={"message": "Muéstrame la plantilla actual"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"].get("table"), "el listado de plantilla no llegó como tabla al mundo 2D"


async def test_a_simple_conversational_reply_never_gets_cards_in_the_2d_world(
    client: Any, services: Any
) -> None:
    """Selección semántica de presentación (requisito 5 de la Fase H): una respuesta puramente
    conversacional (el guion por defecto de `script`, un saludo sin ninguna herramienta de datos) no
    debe llevar tarjetas/tablas/gráficos — nunca cards innecesarias para una charla simple."""
    response = await client.post("/api/mia/chat", json={"message": "Hola, ¿qué tal?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    data = body.get("data") or {}
    assert not data.get("table")
    assert not data.get("cards")
    assert not data.get("charts")
