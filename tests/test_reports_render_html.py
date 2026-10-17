"""Renderizador HTML (Bloque II, Fase E): mismo contrato ``Document``/``Block`` que PDF/XLSX/PPTX,
sin motor de gráficos ni de cálculo paralelo. Cobertura: los 8 tipos de bloque, seguridad XSS,
diseño responsive/accesible/imprimible, y logotipo SBC incrustado de verdad (no solo referenciado)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mia.assets import LOGO
from mia.modules.rrhh.charts import bar_chart, donut_chart, time_series_chart
from mia.modules.rrhh.informes.document import (
    Block,
    Document,
    annex_block,
    methodology_block,
    narrative_block,
    narrative_statement,
    warnings_block,
)
from mia.modules.rrhh.informes.render import RENDERERS

NOW = datetime(2026, 10, 11, 10, 0)


def _html(doc: Document, logo: Path | None = LOGO) -> str:
    return RENDERERS["html"](doc, NOW, logo).decode("utf-8")


def test_html_is_well_formed_and_responsive_and_accessible() -> None:
    doc = Document(title="Informe de prueba", subtitle="Sub", badges=["2026"])
    out = _html(doc)
    assert out.startswith("<!doctype html>")
    assert '<html lang="es">' in out
    assert '<meta name="viewport" content="width=device-width, initial-scale=1" />' in out
    assert "@media print" in out
    assert "@media (max-width:700px)" in out
    assert "<title>Informe de prueba</title>" in out


def test_logo_is_embedded_as_base64_not_referenced_by_path() -> None:
    doc = Document(title="Con logo")
    out = _html(doc, logo=LOGO)
    assert "data:image/png;base64," in out
    assert str(LOGO) not in out  # nunca una ruta de archivo local incrustada en el HTML
    assert 'alt="Logotipo Sunset Beach Club"' in out


def test_html_without_logo_falls_back_to_the_default_sbc_logo() -> None:
    """``resolve_logo()`` exige marca SBC en todo informe (``to_html()``: "Ningún HTML corporativo
    debe salir sin el logotipo embebido") — sin ``logo`` explícito no se omite el `<img>`, se usa el
    logotipo de Sunset Beach Club incluido en el paquete."""
    out = _html(Document(title="Sin logo"), logo=None)
    assert "<img" in out
    assert "data:image/png;base64," in out


def test_xss_in_table_cells_and_titles_is_neutralized() -> None:
    payload = "<script>alert(1)</script>"
    doc = Document(
        title=payload,
        blocks=[Block("table", payload, {"columns": [payload], "rows": [[payload]]})],
    )
    out = _html(doc)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_xss_in_warnings_and_narrative_text_is_neutralized() -> None:
    payload = "<img src=x onerror=alert(1)>"
    doc = Document(
        title="Seguridad",
        blocks=[
            warnings_block("Avisos", [{"severity": "info", "code": "X", "message": payload, "source": "s"}]),
            narrative_block("Hallazgos", [narrative_statement("hypothesis", payload)]),
        ],
    )
    out = _html(doc)
    assert "<img src=x" not in out
    assert "&lt;img src=x onerror=alert(1)&gt;" in out


def test_all_eight_block_kinds_render_with_real_content() -> None:
    doc = Document(
        title="Todos los bloques",
        blocks=[
            Block("kpis", "Indicadores", {"Plantilla": "120", "Absentismo": "4,2%"}),
            Block("section", "Ficha", {"Departamento": "Cocina"}),
            Block("table", "Detalle", {"columns": ["Depto", "Personas"], "rows": [["Cocina", 4], ["Sala", 2]]}),
            Block("chart", "Distribución", donut_chart("Distribución", ["Cocina", "Sala"], [60.0, 40.0])),
            warnings_block("Advertencias", [{"severity": "blocker", "code": "X1", "message": "mensaje de prueba", "source": "s"}]),
            narrative_block("Hallazgos", [narrative_statement("fact", "Dato verificado", evidence={"metric": "m", "value": 1})]),
            methodology_block("Metodología", ["Nota de metodología A"]),
            annex_block("Anexo", ["ID"], [[i] for i in range(10)], max_rows=3),
        ],
    )
    out = _html(doc)
    for expected in (
        "Plantilla", "120", "Ficha", "Cocina", "Detalle", "Sala",
        "Distribución", "BLOQUEANTE", "mensaje de prueba",
        "HECHO VERIFICADO", "Dato verificado", "Metodología", "Nota de metodología A",
        "Anexo", "Mostrando 3 de 10",
    ):
        assert expected in out, f"falta {expected!r} en el HTML"
    # Un gráfico explícito en el documento suprime la auto-derivación heurística para CUALQUIER otra
    # tabla (to_html(): has_explicit_chart, mismo criterio en los 4 renderizadores) — para no mezclar
    # una visualización que el backend decidió a propósito con otras que el renderizador adivinó por
    # su cuenta. Con "Distribución" como chart explícito, "Detalle" NO debe dibujar un segundo SVG.
    assert out.count("<svg") == 1


def test_bar_and_line_charts_render_as_svg() -> None:
    doc = Document(
        title="Gráficos",
        blocks=[
            Block("chart", "Barras", bar_chart("Barras", ["A", "B", "C"], [1.0, 2.0, 3.0])),
            Block("chart", "Línea", time_series_chart("Línea", ["ene", "feb", "mar"], [{"name": "v", "values": [1.0, 2.0, 1.5]}])),
        ],
    )
    out = _html(doc)
    assert out.count("<svg") == 2
    assert "<rect" in out  # barras
    assert "<path" in out  # línea


def test_annex_without_truncation_has_no_notice() -> None:
    doc = Document(title="Anexo", blocks=[annex_block("Detalle", ["ID"], [[1], [2]], max_rows=10)])
    out = _html(doc)
    assert "Mostrando" not in out
