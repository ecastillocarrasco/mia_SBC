"""Un bloque ``table``/``annex`` puede llevar un resumen de indicadores adjunto
(``data["kpis"]``, ver docstring de ``Block``): tarjetas KPI justo antes de su propia tabla, bajo el
MISMO título — nunca un bloque ``kpis`` aparte, que en Excel/PowerPoint se convertiría en una
pestaña/diapositiva propia para lo que es un resumen de ESTA tabla, no una sección independiente.

Pensado para informes con una entidad por bloque (una persona, un proyecto…) — ver
``mia.modules.rrhh.fichajes.informe._build_document`` para el caso real que motivó esto: regresión
descubierta ahí fue que las tarjetas KPI (posicionadas igual que para un bloque "kpis" independiente,
a la derecha de una tabla estrecha Concepto/Valor) colisionaban con las columnas de una tabla ANCHA
(detalle diario, 11 columnas) en Excel, solapando datos. Estos tests fijan el comportamiento correcto.

All values are synthetic. No corporate data, network access, or live LLM calls.
"""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import load_workbook

from mia.reporting.document import Block, Document
from mia.reporting.render import to_pdf, to_pptx, to_xlsx
from mia.reporting.render_docx import to_docx
from mia.reporting.render_html import to_html

NOW = datetime(2026, 10, 25)

# Una tabla ANCHA (6 columnas) a propósito: la tabla estrecha Concepto/Valor que usa un bloque "kpis"
# independiente nunca habría revelado la colisión de columnas en Excel.
WIDE_TABLE_KPIS = {
    "Horas programadas": 40,
    "Horas trabajadas": 39,
    "Balance": "-1,00 h",
    "Balance % turno": "-2,5%",
    "Correctos": 4,
    "Desviados": 1,
}
WIDE_TABLE = Block(
    "table",
    "Melania Rosello Diaz",
    {
        "columns": ["Fecha", "Estado", "Turno", "Entrada", "Salida", "Balance"],
        "rows": [
            ["lun 12/10/2026", "correcto", "Piscina 10-18", "10:00", "18:00", "+0,00"],
            ["mar 13/10/2026", "desviado", "Piscina 10-18", "10:20", "18:00", "-0,33"],
        ],
        "kpis": WIDE_TABLE_KPIS,
    },
)


def make_document() -> Document:
    return Document(
        "Informe comparativo turnos · fichajes — Restaurante",
        subtitle="Periodo de prueba",
        badges=["Restaurante"],
        blocks=[
            Block("kpis", "Resumen ejecutivo · Restaurante", {"Personas analizadas": 1}),
            WIDE_TABLE,
        ],
    )


def test_xlsx_kpi_cards_sit_above_the_table_never_overlapping_its_columns():
    wb = load_workbook(io.BytesIO(to_xlsx(make_document(), NOW)))
    assert wb.sheetnames == ["Resumen ejecutivo · Restaurante", "Melania Rosello Diaz"]
    ws = wb["Melania Rosello Diaz"]
    # 6 indicadores a 3 por fila = 2 "bandas" de 5 filas, empezando en la fila 6 → la cabecera de la
    # tabla debe empezar justo después, no solapada con las tarjetas.
    assert ws.cell(16, 1).value == "Fecha"
    assert ws.cell(17, 1).value == "lun 12/10/2026"
    # Las tarjetas están realmente ahí (no se perdieron al desplazar la tabla).
    labels = {ws.cell(r, c).value for r in range(6, 16) for c in (1, 5, 9)}
    assert "Horas programadas" in labels and "Correctos" in labels
    values = {ws.cell(r, c).value for r in range(6, 16) for c in (1, 5, 9)}
    assert 40 in values  # Horas programadas: valor numérico real, no texto
    # Ninguna celda de las columnas de la tabla ancha (hasta F) quedó pisada por una tarjeta: las
    # filas de tarjetas (6-15) en las columnas B-D y F-H deben estar vacías (zona de separación).
    for r in range(6, 16):
        assert ws.cell(r, 4).value is None  # columna D: hueco entre tarjeta 1 y 2


def test_xlsx_standalone_kpis_block_is_unaffected_by_the_sidecar_feature():
    """El bloque "kpis" independiente (sin tabla ancha emparejada) sigue con tarjetas
    vinculadas por fórmula a su propia tabla Concepto/Valor, en la fila 7 de siempre."""
    wb = load_workbook(io.BytesIO(to_xlsx(make_document(), NOW)))
    ws = wb["Resumen ejecutivo · Restaurante"]
    assert ws["B7"].value == 1
    assert ws["E8"].value == "=B7"


def test_pdf_kpi_cards_and_table_share_a_single_heading_not_two():
    content = to_pdf(make_document(), NOW)
    from pypdf import PdfReader  # noqa: PLC0415

    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    assert text.count("Melania Rosello Diaz") == 1
    assert "Horas programadas" in text
    assert "lun 12/10/2026" in text


def test_docx_kpi_cards_render_as_a_table_before_the_detail_table_under_one_heading():
    from docx import Document as WordDocument  # noqa: PLC0415

    word = WordDocument(io.BytesIO(to_docx(make_document(), NOW)))
    headings = [p.text for p in word.paragraphs if p.style.name.startswith("Heading")]
    assert headings.count("Melania Rosello Diaz") == 1
    kpi_table, detail_table = word.tables[-2], word.tables[-1]
    assert "40" in kpi_table.cell(0, 0).text
    assert detail_table.cell(0, 0).text == "Fecha"


def test_pptx_kpi_slide_and_table_slide_share_the_same_title_consecutively():
    from pptx import Presentation  # noqa: PLC0415

    deck = Presentation(io.BytesIO(to_pptx(make_document(), NOW)))
    titled = [
        (
            i,
            next(
                (sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and "Melania" in sh.text_frame.text),
                None,
            ),
        )
        for i, slide in enumerate(deck.slides)
    ]
    melania_slides = [i for i, title in titled if title]
    assert len(melania_slides) >= 2  # al menos la de tarjetas + la de detalle
    assert melania_slides == sorted(melania_slides)  # consecutivas, no intercaladas con otra persona


def test_html_kpi_grid_renders_before_the_table_under_the_same_heading():
    html = to_html(make_document(), NOW).decode("utf-8")
    assert html.count(">Melania Rosello Diaz<") == 1
    kpi_pos = html.index("kpi-grid")
    table_pos = html.index("<table>")
    assert kpi_pos < table_pos
