"""Regresión del incidente real (trace mia-20261012-115403-bad97707): "exporta a pdf el informe
anterior" terminaba con respuesta HTTP "ok" pero sin presentaciones ni archivo (el síntoma exacto
descrito: "respuesta HTTP/operativa general aparentemente correcta, pero sin presentaciones ni
archivos generados").

Causa raíz nº1 (de las dos identificadas en esta investigación — ver `test_period_label_locale_
consistency.py` para la causa raíz nº2): cuando el modelo pide "un informe completo" y el router
elige `generar_informe_ejecutivo` en vez de `analisis_economico_nominas` directamente, la redirección
real de la sección 15 SÍ genera el PDF económico correcto en ese turno — pero la tabla real del
análisis (`eco_result.presentation`, con KPIs/gráficos/departamentos) solo vivía en una variable
local de `_redirect_to_economic_analysis()`. `remember_table()` descarta a propósito el resultado
`{"type":"download"}` de ESE mismo informe (ya generado, nada que re-exportar) — así que la tabla real
nunca llegaba a `session_state`. Una petición posterior en OTRO turno ("exporta de nuevo") no
encontraba ningún resultado que exportar (`generar_informe` devolvía `NOT_FOUND`).

Corrección: `_redirect_to_economic_analysis()` (`src/mia/modules/rrhh/informes/tools.py`) ahora llama
a `remember_table()` con la tabla REAL del análisis económico antes de renderizar el informe ejecutivo
— el mismo patrón que ya usa `run_informe_economico_nominas` (Job Manager, Fase G) por la misma razón.
"""

from __future__ import annotations

import json

import httpx

import mia.diagnostics as diag
from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.data import Payslip
from mia.diagnostics import EventStage
from mia.llm.base import LLMCompleted, LLMRequest, ToolCall, ToolCallRequested
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.main import create_app
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.hr_seed import _emp
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss


async def _build_repro_app(tmp_path, scripted):
    db = await fresh_database(tmp_path, "incident_repro.db")
    async with db.session() as s:
        sp_id = 5000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 5000
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
    llm = FakeLLMProvider(scripted)
    settings = make_settings(
        tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'incident_repro.db'}",
        diagnostics={"enabled": True, "admin_users": ["admin@test.local"], "admin_password": "test-password"},
    )

    from mia.api.services import Services
    from mia.conversation import ConversationEngine, Persona
    from mia.modules.registry import build_registry

    services = Services.build(settings, llm=llm, db=db)
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
    return app, sp, db


async def test_turn1_via_executive_redirect_then_turn2_export_delivers_the_real_report(tmp_path) -> None:
    """Turno 1: el modelo elige `generar_informe_ejecutivo` (no `analisis_economico_nominas`
    directamente) para "Genera un informe completo..." — exactamente el router real de la sección 15.
    Turno 2, misma sesión: "Exporta a pdf el informe anterior". Antes de la corrección, el turno 2
    terminaba con `status="ok"` pero `data`/`actions`/`presentations` vacíos — nunca un error visible,
    solo un resultado vacío en silencio."""
    turn_counter = {"n": 0}

    def scripted(req: LLMRequest):
        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            turn_counter["n"] += 1
            if turn_counter["n"] == 1:
                return [
                    ToolCallRequested(
                        ToolCall(
                            "call_1",
                            "generar_informe_ejecutivo",
                            json.dumps({"periodo": "agosto de 2026", "formato": "pdf"}),
                        )
                    ),
                    LLMCompleted(),
                ]
            return tool_call("generar_informe", {"formato": "pdf", "incluir_detalle": True, "incluir_grafico": True})
        return final_answer("Aquí tienes el informe.", "Listo.")

    app, sp, db = await _build_repro_app(tmp_path, scripted)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                first = await client.post(
                    "/api/mia/chat",
                    json={
                        "message": "Genera un informe completo de comparativa de costes en nóminas por departamento en agosto de 2026"
                    },
                )
                assert first.status_code == 200
                first_body = first.json()
                assert first_body["status"] == "ok"
                assert first_body["presentations"], "el turno 1 (redirección ejecutiva) no generó ningún informe"
                session_id = first_body["context"]["session_id"]

                second = await client.post(
                    "/api/mia/chat",
                    json={"message": "Exporta a pdf el informe anterior", "context": {"session_id": session_id}},
                )
                assert second.status_code == 200
                second_body = second.json()
                assert second_body["status"] == "ok"
                # El síntoma exacto de la incidencia: antes de la corrección, esto estaba vacío.
                assert second_body["presentations"], "turno 2: sin presentaciones — el síntoma exacto de la incidencia"
                assert second_body["actions"], "turno 2: sin acción de descarga"
                # Debe ser el informe económico real (el título que construye analisis_economico_nominas),
                # nunca el informe ejecutivo genérico ni un documento vacío.
                assert "Gasto salarial por departamento" in second_body["presentations"][0]["title"]

            traces = diag._store.list()
            statuses = [
                ev.data.get("status")
                for rec in traces
                for ev in rec.events
                if ev.stage in (EventStage.TOOL_CALL_COMPLETE, EventStage.TOOL_CALL_ERROR)
                and ev.data.get("tool") == "generar_informe"
            ]
            assert statuses and all(s == "ok" for s in statuses), f"generar_informe no completó con 'ok': {statuses}"
    finally:
        await sp.aclose()
        await db.dispose()
