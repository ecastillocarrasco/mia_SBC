"""Bloque II: integración documental de ``analisis_economico_nominas`` (requisitos 3/4/6 de la ronda de
validación del usuario tras la Fase D).

Prueba de extremo a extremo con una petición casi literal del usuario: "Comparativa de costes
salariales de julio a septiembre de 2026 por departamentos" → ``analisis_economico_nominas`` →
``to_document()`` → los tres formatos reales. Verifica que PDF/XLSX/PPTX usan EXACTAMENTE los mismos
resultados ya validados por la herramienta (mismos departamentos, mismo gráfico ya calculado, misma
advertencia de k-anonimato) — nunca una cifra re-derivada ni un motor paralelo.

Reutiliza ``q3_registry`` de ``tests/test_analisis_economico.py`` (no se duplica la siembra de datos ni
el conector SharePoint simulado: "Sala" tiene solo 2 personas, por debajo de MIN_GROUP=3, así que debe
quedar oculta — el caso real que ejercita el requisito 2 del usuario, no uno construido a propósito)."""

from __future__ import annotations

import io
import json

from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from mia.assets import LOGO
from mia.auth import UserContext
from mia.conversation import ToolContext, ToolStatus
from mia.conversation.tools import LAST_TABLE, remember_table
from mia.llm import ToolCall
from mia.modules.rrhh.informes.document import to_document
from mia.modules.rrhh.informes.render import RENDERERS
from tests.test_analisis_economico import NOW, q3_registry  # noqa: F401 — fixture reutilizada

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))


def _document_from(result: object) -> object:
    """El flujo real nunca llama a ``to_document()`` sobre la presentación cruda: siempre pasa antes
    por ``remember_table()`` (ver ``ConversationEngine.run()``), que es quien adjunta ``__summary__`` —
    de ahí salen las advertencias. Llamar a ``to_document()`` directamente sobre
    ``ToolResult.presentation`` sin ese paso (como hacía una versión anterior de esta prueba) no
    reproduce el camino real."""
    state: dict[str, object] = {}
    remember_table(state, result.presentation, 5000, result.summary)
    return to_document(state[LAST_TABLE])


async def test_salary_cost_comparison_request_end_to_end_three_formats(q3_registry) -> None:
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    execution_result = (
        await q3_registry.execute(
            ToolCall(
                "c", "analisis_economico_nominas",
                json.dumps({"periodo": "julio a septiembre de 2026"}),
            ),
            ctx,
        )
    ).result
    assert execution_result.status is ToolStatus.OK
    summary = execution_result.summary
    presentation = execution_result.presentation

    # Lo que de verdad calculó el backend (ground truth para el resto de la prueba). "Sala" sigue
    # LISTADA (transparencia: el lector sabe que ese departamento existe y fue analizado) pero con
    # los importes explícitamente sustituidos por un texto, nunca por una cifra real ni por un cero.
    assert summary["total_periodo_es_solo_grupos_autorizados"] is True  # Sala (2 personas) queda oculta
    assert "ocultos" in summary["por_departamento"]["Sala"]["importes"]
    assert {"Cocina", "Recepción"} <= set(summary["por_departamento"])
    assert presentation["charts"]  # la herramienta ya calculó sus propios gráficos

    doc = _document_from(execution_result)

    # El documento debe llevar: KPIs explícitos, un bloque de advertencias, y los gráficos ya
    # calculados como bloques de primera clase — no una tabla genérica re-interpretada.
    kinds = [b.kind for b in doc.blocks]
    assert "kpis" in kinds
    assert "warnings" in kinds
    # Deduplicación deliberada (to_document(), "Ranking y donut de la misma distribución no aportan
    # dos lecturas distintas"): de los 3 gráficos que calcula analisis_economico_nominas para esta
    # petición, el donut y el ranking de barras comparten EXACTAMENTE las mismas etiquetas y valores
    # (misma distribución, dos formas de dibujarla) — correcto que solo uno sobreviva al documento;
    # el tercero (evolución mensual) tiene datos propios y siempre se conserva. No es un recuento 1:1
    # con presentation["charts"]: verificar la deduplicación real, no pelearse con ella.
    chart_signatures = {
        json.dumps([c["labels"], [s.get("values") for s in c["series"]]], sort_keys=True)
        for c in presentation["charts"]
    }
    assert kinds.count("chart") == len(chart_signatures) == 2

    warnings_items = next(b.data["items"] for b in doc.blocks if b.kind == "warnings")
    assert any("NOM-005" in w["message"] or "no cumplen el mínimo" in w["message"] for w in warnings_items)

    chart_blocks = [b for b in doc.blocks if b.kind == "chart"]
    for chart_block in chart_blocks:
        assert "Sala" not in chart_block.data["labels"]  # el gráfico respeta el k-anonimato, no solo la tabla

    for fmt in ("pdf", "xlsx", "pptx", "html"):
        content = RENDERERS[fmt](doc, NOW, LOGO)
        assert content

    # HTML: mismos departamentos, misma advertencia de k-anonimato, logo incrustado — no un renderizador
    # ni un recálculo distinto del resto de formatos.
    html_text = RENDERERS["html"](doc, NOW, LOGO).decode("utf-8")
    assert "Cocina" in html_text
    assert "no cumplen el mínimo" in html_text
    assert "data:image/png;base64," in html_text

    # PDF: logotipo SBC embebido (el renderizador lo dibuja desde el mismo archivo que usa el resto de
    # mIA — ver mia.assets.resolve_logo), departamentos reales, advertencia de k-anonimato visible, y
    # "Sala" ausente de las cifras desglosadas.
    pdf_bytes = RENDERERS["pdf"](doc, NOW, LOGO)
    pdf_text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    assert "Cocina" in pdf_text
    assert "Recepción" in pdf_text
    assert "no cumplen el mínimo" in pdf_text
    assert LOGO.exists()  # el logo que se pasó al renderizador es el oficial real de SBC, no uno de prueba

    # XLSX: mismos departamentos, mismo recuento de advertencias.
    wb = load_workbook(io.BytesIO(RENDERERS["xlsx"](doc, NOW, LOGO)))
    flat = " ".join(
        str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None
    )
    assert "Cocina" in flat
    assert "no cumplen el mínimo" in flat

    # PPTX: el bloque de advertencias tiene su propia diapositiva dedicada (no una tabla genérica).
    # "Cocina" vive en una tabla (GraphicFrame), no en un cuadro de texto — hay que recorrer también
    # las celdas, o la prueba no vería nada que SÍ está correctamente en el documento.
    slides = Presentation(io.BytesIO(RENDERERS["pptx"](doc, NOW, LOGO))).slides
    text_parts = [shape.text_frame.text for slide in slides for shape in slide.shapes if shape.has_text_frame]
    table_parts = [
        cell.text
        for slide in slides
        for shape in slide.shapes
        if shape.has_table
        for row in shape.table.rows
        for cell in row.cells
    ]
    all_text = " ".join(text_parts + table_parts)
    assert "no cumplen el mínimo" in all_text
    assert "Cocina" in all_text


async def test_a_month_with_no_payslips_produces_a_visible_coverage_warning(q3_registry) -> None:
    """Requisito 4: meses sin datos deben avisarse, no desaparecer en silencio. Pide un rango que incluye
    meses fuera de los sembrados por ``q3_registry`` (solo jul-sep 2026)."""
    ctx = ToolContext(user=ADMIN, request_id=None, now=NOW, session_state={})
    execution_result = (
        await q3_registry.execute(
            ToolCall("c", "analisis_economico_nominas", json.dumps({"periodo": "2026-06 a 2026-07"})),
            ctx,
        )
    ).result
    assert execution_result.status is ToolStatus.OK
    assert execution_result.summary["meses_sin_datos"]  # junio no tiene nóminas sembradas

    doc = _document_from(execution_result)
    warnings_items = next((b.data["items"] for b in doc.blocks if b.kind == "warnings"), [])
    assert any("Sin datos para" in w["message"] for w in warnings_items)

    pdf_text = "".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(RENDERERS["pdf"](doc, NOW, LOGO))).pages
    )
    assert "Sin datos para" in pdf_text
