"""Pruebas sintéticas del mismo motor de informes; nunca datos reales ni credenciales."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from io import BytesIO

import openpyxl
import pytest
from pptx import Presentation

from mia.conversation.tools import LAST_TABLE, remember_table
from mia.llm.base import TextDelta
from mia.modules.rrhh.nominas.analisis_economico import _group_stats
from mia.reporting import content_composer
from mia.reporting.document import Block, Document, to_document
from mia.reporting.render import to_pdf, to_pptx, to_xlsx
from mia.reporting.render_html import to_html

NOW = datetime(2026, 10, 14)
SERIES = {
    "type": "line",
    "title": "Comparativa",
    "labels": ["2025", "2026"],
    "series": [{"name": "Sistemas", "values": [123.40, 140.25]}, {"name": "Operaciones", "values": [230.40, 260.25]}],
}


def test_saved_session_rows_not_mutated_and_export_metadata_marks_truncation():
    original = {
        "type": "dashboard",
        "title": "Panel",
        "tables": [
            {"title": "Detalle", "columns": ["n"], "rows": [[n] for n in range(6)]},
        ],
    }
    state = {}
    remember_table(state, original, 3, {"ok": True}, source_tool="some_tool")
    assert len(original["tables"][0]["rows"]) == 6
    assert len(state[LAST_TABLE]["tables"][0]["rows"]) == 3
    assert state[LAST_TABLE]["__export_meta__"]["truncated"]
    assert state[LAST_TABLE]["__export_meta__"]["tables"][0]["total"] == 6


def test_distinct_people_not_person_months():
    stats = _group_stats([100.0] * 6, 2, False, 3)
    assert stats["personas_con_nomina"] == 2
    assert stats["observaciones_nomina"] == 6
    assert _group_stats([1, 2, 3], 1, True, 3)["personas_con_nomina"] == 1


def test_duplicate_graphs_not_repeated():
    d = to_document(
        {
            "type": "table",
            "title": "Datos",
            "columns": ["Depto", "Total"],
            "rows": [["Sistemas", 10], ["Operaciones", 20]],
            "charts": [
                {
                    "type": "donut",
                    "title": "Distribución",
                    "labels": ["A", "B"],
                    "series": [{"name": "Total", "values": [10, 20]}],
                },
                {
                    "type": "bar",
                    "title": "Ranking",
                    "labels": ["A", "B"],
                    "series": [{"name": "Total", "values": [10, 20]}],
                },
            ],
        }
    )
    assert sum(b.kind == "chart" for b in d.blocks) == 1


def test_exports_preserve_chart_series_and_excel_numeric_values():
    doc = Document(
        "Informe sintético",
        [
            Block("chart", "Comparativa", SERIES),
            Block(
                "table",
                "Importes",
                {"columns": ["Nombre", "Importe", "%"], "rows": [["Sistemas", "9.087,57 €", "56,0%"]]},
            ),
            Block("kpis", "Indicadores", {f"Métrica {i}": i for i in range(16)}),
        ],
    )
    xlsx = to_xlsx(doc, NOW)

    wb = openpyxl.load_workbook(BytesIO(xlsx))
    assert len(wb.worksheets[0]._charts[0].series) == 2
    assert wb.worksheets[1]["B7"].value == 9087.57
    assert wb.worksheets[1]["C7"].value == 0.56
    assert len({ws.title for ws in wb.worksheets}) == len(wb.worksheets)
    pptx = to_pptx(doc, NOW)

    ppt = Presentation(BytesIO(pptx))
    charts = [sh.chart for slide in ppt.slides for sh in slide.shapes if sh.has_chart]
    assert charts and len(charts[0].series) == 2
    assert "Métrica 15" in " ".join(sh.text for slide in ppt.slides for sh in slide.shapes if sh.has_text_frame)
    pdf = to_pdf(doc, NOW)
    assert pdf.startswith(b"%PDF")
    html = to_html(doc, NOW)
    assert "Operaciones" in html.decode("utf-8")
    assert "Sistemas" in html.decode("utf-8")


def test_long_pptx_cells_are_not_truncated():
    long = "detalles-importantes-" * 30
    doc = Document("Longitud", [Block("table", "Texto", {"columns": ["Código", "Detalle"], "rows": [["A", long]]})])
    output = to_pptx(doc, NOW)

    p = Presentation(BytesIO(output))
    rendered = []
    for slide in p.slides:
        for shape in slide.shapes:
            if shape.has_table:
                for row in shape.table.rows:
                    cells = [cell.text for cell in row.cells]
                    if cells[0] == "Código":
                        continue
                    rendered.append(cells[1])
    assert "".join(rendered) == long


@pytest.fixture(scope="module")
def _fake_llm_stack():
    """Usa el compositor real y fija solo la elección de modelo, sin red."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(content_composer, "model_for_tier", lambda _settings, _tier: "gpt-4.1")
        yield content_composer


def test_composer_selects_only_requested_blocks_and_preserves_warnings(_fake_llm_stack):
    # La selección usa el proveedor ya inyectado; se simula su API sin conexión externa.

    composer = _fake_llm_stack

    doc = Document(
        "Informe RRHH",
        [
            Block("table", "Plantilla por departamento", {"columns": ["D", "N"], "rows": [["A", 10]]}),
            Block("table", "Absentismo", {"columns": ["Tipo", "Dias"], "rows": [["IT", 20]]}),
            Block("warnings", "Advertencias", {"items": [{"severity": "info", "code": "X", "message": "Diferencias"}]}),
        ],
    )

    class FakeLLM:
        async def stream(self, request):
            assert request.model == "gpt-4.1"
            assert "20" not in request.messages[0].content  # no importes ni valores a LLM
            yield TextDelta(json.dumps({"selected_indices": [1], "unavailable": []}))

    result = asyncio.run(
        composer.compose_for_request(doc, "Informe solo de absentismo", FakeLLM(), llm_settings=object())
    )
    assert [block.title for block in result.blocks] == ["Absentismo", "Advertencias"]
    assert len(doc.blocks) == 3  # copia inmutable


def test_composer_fails_closed_for_unavailable_requested_metrics(_fake_llm_stack):

    composer = _fake_llm_stack

    class FakeLLM:
        async def stream(self, request):
            yield TextDelta(json.dumps({"selected_indices": [0], "unavailable": ["Coste salarial"]}))

    doc = Document(
        "Ejemplo",
        [
            Block("table", "Empleados", {"columns": ["Nombre"], "rows": [["X"]]}),
            Block("table", "Turnos", {"columns": ["Fecha"], "rows": [["2026"]]}),
        ],
    )
    with pytest.raises(composer.MissingReportEvidence):
        asyncio.run(composer.compose_for_request(doc, "Informe de coste salarial", FakeLLM()))
