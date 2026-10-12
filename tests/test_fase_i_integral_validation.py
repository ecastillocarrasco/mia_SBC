"""Fase I del Bloque II (Advanced Reporting Engine): validación funcional integral.

El usuario pidió explícitamente "pruebas completas desde la solicitud del usuario hasta el informe
descargado, incluyendo su correspondencia exacta con los datos mostrados en el mundo 2D". Lo que ya
existía antes de esta fase no cubría eso del todo:

- `tests/test_report_routing_semantic_validation.py::test_salary_cost_comparison_for_august_two_
  thousand_twenty_six_end_to_end_four_formats` prueba los 4 formatos (PDF/XLSX/PPTX/HTML) pero
  llamando a las herramientas DIRECTAMENTE (`ToolCall`), no a través de `/api/mia/chat` — nunca pasa
  por el mundo 2D real.
- `tests/test_fase_h_2d_presentation.py::test_background_job_request_is_queued_tracked_and_
  downloadable_from_the_2d_world` sí pasa por `/api/mia/chat` y descarga un PDF real, pero solo
  comprueba nombres de departamento ("Cocina"/"Recepción"), nunca una CIFRA exacta, y solo PDF, y solo
  mediante el camino de trabajo en segundo plano (no el camino normal, directo, de la mayoría de
  peticiones).

Esta fase añade lo que faltaba: la petición de la incidencia, en lenguaje natural, a través de
`/api/mia/chat` (el punto de entrada real del mundo 2D), con descarga INMEDIATA (sin Job Manager, el
camino que sigue la mayoría de peticiones) en los 4 formatos, comprobando que la MISMA cifra exacta de
KPI que aparece en `data.cards` en pantalla aparece también, literalmente, dentro del documento
descargado — nunca una sustitución silenciosa ni una cifra distinta. Y lo mismo para un dominio no
económico (Turnos), con un dato operativo transcrito literalmente.
"""

from __future__ import annotations

import io

import httpx
import pytest
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from mia.connectors.sharepoint import SharePointClient, StaticTokenProvider
from mia.data import Payslip
from mia.llm.fake import FakeLLMProvider, final_answer, tool_call
from mia.main import create_app
from tests.conftest import make_settings
from tests.dbutil import fresh_database
from tests.hr_seed import _emp, seed
from tests.test_phase4b import _pdf
from tests.test_report_routing_semantic_validation import _AUG_DEPARTMENTS, _payslip_text_with_ss

INCIDENT_REQUEST = (
    "Genera un informe completo de comparativa de costes en nóminas por departamento en agosto de 2026"
)


async def _build_payroll_chat_app(tmp_path, *, formato: str, db_name: str):
    """Mismo escenario sintético de agosto de 2026 (con cotizaciones SS reales) que
    `tests/test_fase_h_2d_presentation.py::chat_app`, con el LLM simulado encadenando
    `analisis_economico_nominas` → `generar_informe` con el formato pedido → respuesta final, en el
    MISMO turno — el camino directo que sigue la mayoría de peticiones, no el de segundo plano."""
    db = await fresh_database(tmp_path, db_name)
    async with db.session() as s:
        sp_id = 8000
        for dept, people in _AUG_DEPARTMENTS.items():
            position = "Cocinero" if dept == "Cocina" else "Recepcionista"
            for pk in people:
                sp_id += 1
                s.add(_emp(sp_id, f"Empleado {pk}", dept, position=position, person_key=pk))
                s.add(Payslip(sp_id=sp_id, person_key=pk, year=2026, month=8, period="2026-08", special=False))

    net_by_sp_id: dict[int, float] = {}
    sp_id = 8000
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
        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("analisis_economico_nominas", {"periodo": "agosto de 2026", "concepto": "coste_empresa"})
        if len(tool_rounds) == 1:
            return tool_call("generar_informe", {"formato": formato})
        return final_answer("Aquí tienes la comparativa de costes por departamento.", "Listo.")

    llm = FakeLLMProvider(scripted)
    settings = make_settings(tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / db_name}")

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
    return app, sp, db


def _download_action(body: dict) -> dict:
    for action in body.get("actions") or []:
        if action.get("type") == "download":
            return action
    raise AssertionError(f"no se encontró una acción de descarga en actions: {body.get('actions')}")


@pytest.mark.parametrize("formato", ["pdf", "xlsx", "pptx", "html"])
async def test_screen_kpi_figure_matches_the_downloaded_document_exactly(tmp_path, formato: str) -> None:
    """Petición en lenguaje natural, por `/api/mia/chat` (mundo 2D real), descarga inmediata (sin
    segundo plano) en cada uno de los 4 formatos: la cifra EXACTA del KPI "Gasto total" mostrado en
    `data.cards` debe aparecer, literalmente, dentro del documento descargado."""
    app, sp, db = await _build_payroll_chat_app(tmp_path, formato=formato, db_name=f"fase_i_{formato}.db")
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/mia/chat", json={"message": INCIDENT_REQUEST})
                assert response.status_code == 200
                body = response.json()
                data = body["data"]

                cards = data.get("cards") or []
                total_card = next((c for c in cards if "gasto total" in c["label"].lower()), None)
                assert total_card is not None, f"no se encontró el KPI de gasto total en pantalla: {cards}"
                screen_figure = total_card["value"]
                assert "€" in screen_figure  # es la cifra formateada, no solo un número suelto

                action = _download_action(body)
                assert action["url"].startswith("/api/reports/")
                download = await client.get(action["url"])
                assert download.status_code == 200
        content = download.content

        if formato == "pdf":
            text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        elif formato == "xlsx":
            wb = load_workbook(io.BytesIO(content))
            text = " ".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None)
        elif formato == "pptx":
            slides = Presentation(io.BytesIO(content)).slides
            parts = []
            for slide in slides:
                for shape in slide.shapes:
                    if shape.has_table:
                        parts += [cell.text for row in shape.table.rows for cell in row.cells]
                    elif shape.has_text_frame:
                        parts.append(shape.text_frame.text)
            text = " ".join(parts)
        else:
            text = content.decode("utf-8")

        assert "Cocina" in text
        assert "Recepción" in text
        assert screen_figure in text, (
            f"la cifra mostrada en pantalla ({screen_figure!r}) no aparece literalmente en el "
            f"documento {formato} descargado — posible sustitución o inconsistencia de cifras"
        )
    finally:
        await sp.aclose()
        await db.dispose()


async def test_screen_table_value_matches_the_downloaded_document_for_a_non_payroll_domain(tmp_path) -> None:
    """Mismo tipo de correspondencia exacta pantalla↔documento, para un dominio NO económico
    (ausencias/Turnos): el periodo mostrado en `data.table` debe aparecer también, literalmente, en el
    PDF descargado — no solo para nóminas."""
    db = await fresh_database(tmp_path, "fase_i_ausencias.db")
    await seed(db)

    def scripted(req):
        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("ausencias", {"nombre": "Eva Sol", "desde": "2026-08-03", "hasta": "2026-08-06"})
        if len(tool_rounds) == 1:
            return tool_call("generar_informe", {"formato": "pdf"})
        return final_answer("Aquí tienes el informe de ausencias.", "Listo.")

    llm = FakeLLMProvider(scripted)
    settings = make_settings(tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / 'fase_i_ausencias.db'}")

    from mia.api.services import Services

    services = Services.build(settings, llm=llm, db=db)
    app = create_app(settings, services=services)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/mia/chat", json={"message": "Informe de ausencias de Eva Sol la primera semana de agosto"}
                )
                assert response.status_code == 200
                body = response.json()
                data = body["data"]
                table = data.get("table")
                assert table and table.get("rows"), "el resultado de ausencias no llegó como tabla al mundo 2D"
                screen_row = table["rows"][0]
                screen_name = screen_row.get("Persona") or screen_row.get("Empleado") or screen_row.get("Nombre")
                assert screen_name, f"la tabla en pantalla no trae el nombre de la persona: {screen_row}"

                action = _download_action(body)
                download = await client.get(action["url"])
                assert download.status_code == 200
        pdf_text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(download.content)).pages)
        assert screen_name in pdf_text, (
            f"el nombre mostrado en pantalla ({screen_name!r}) no aparece literalmente en el PDF descargado"
        )
    finally:
        await services.aclose()
