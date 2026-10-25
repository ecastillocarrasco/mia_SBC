"""Renderizadores corporativos (PDF, Excel, PowerPoint, HTML y Word) para el modelo documental común.

Cabecera con el logo de Sunset Beach Club en todas las páginas, filete dorado, secciones con marca, tarjetas de
indicadores y gráficos incrustados cuando el resultado es un recuento por categorías o una serie temporal.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from mia.assets import resolve_logo
from mia.reporting.charts import chart_spec
from mia.reporting.document import Block, Document
from mia.reporting.render_html import to_html
from mia.reporting.render_docx import to_docx

NAVY = "1B2559"
GOLD = "D8A565"
LIGHT = "F6F3EE"
LINE = "E3DDD3"
MUTED = "6B6F80"
PALETTE = ["1B2559", "D8A565", "3A8F8A", "D9776B", "5B8DEF", "8A6BB0", "7FA37A", "C9B8A3"]

# Colores de severidad para Block(kind="warnings") — sección 9/condición 2 de la aprobación de Fase D:
# bloqueante, calidad de datos e información deben distinguirse visualmente, no solo en el dato crudo.
SEVERITY_COLOR = {"blocker": "B3261E", "data_quality": "A66A1E", "info": "3A8F8A"}
SEVERITY_LABEL = {"blocker": "BLOQUEANTE", "data_quality": "CALIDAD DE DATOS", "info": "INFO"}
NARRATIVE_LABEL = {
    "fact": "HECHO VERIFICADO", "interpretation": "INTERPRETACIÓN",
    "hypothesis": "HIPÓTESIS", "recommendation": "RECOMENDACIÓN",
}


def _flat_evidence(evidence: dict[str, Any]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in evidence.items()) if evidence else "—"


def _rows(block: Block) -> tuple[list[str], list[list[Any]]]:
    if block.kind in ("table", "annex"):
        return [str(c) for c in block.data.get("columns", [])], list(block.data.get("rows", []))
    if block.kind == "chart":
        # Reconstrucción de la tabla de datos que respalda el gráfico (sección 9: el gráfico y su
        # tabla deben venir del mismo cálculo, nunca inventarse por separado) — ver ``Block.kind ==
        # "chart"`` en el docstring de ``Block``.
        spec = block.data
        series = spec.get("series", [])
        labels = spec.get("labels", [])
        columns = ["Categoría", *(str(s.get("name", "Valor")) for s in series)]
        rows = [
            [label, *(s.get("values", [None] * len(labels))[i] for s in series)]
            for i, label in enumerate(labels)
        ]
        return columns, rows
    if block.kind == "warnings":
        columns = ["Severidad", "Código", "Mensaje", "Fuente"]
        rows = [
            [SEVERITY_LABEL.get(i.get("severity"), i.get("severity")), i.get("code"), i.get("message"), i.get("source", "")]
            for i in block.data.get("items", [])
        ]
        return columns, rows
    if block.kind == "narrative":
        columns = ["Tipo", "Afirmación", "Evidencia"]
        rows = [
            [NARRATIVE_LABEL.get(s.get("kind"), s.get("kind")), s.get("text"), _flat_evidence(s.get("evidence") or {})]
            for s in block.data.get("statements", [])
        ]
        return columns, rows
    if block.kind == "methodology":
        return ["Metodología"], [[n] for n in block.data.get("notes", [])]
    return ["Concepto", "Valor"], [[k, v] for k, v in block.data.items()]


def _chart_segments(spec: dict[str, Any], max_labels: int = 15) -> list[dict[str, Any]]:
    """Split oversized figures without dropping categories or changing source values.

    Donuts with many sectors are changed to grouped horizontal bars: percentages of
    separate donut pages would be misleading, while absolute values remain intact.
    """
    labels = list(spec.get("labels") or [])
    if len(labels) <= max_labels:
        return [spec]
    result: list[dict[str, Any]] = []
    chart_type = "horizontal_bar" if spec.get("type") == "donut" else spec.get("type")
    for start in range(0, len(labels), max_labels):
        end = min(start + max_labels, len(labels))
        result.append({
            **spec,
            "type": chart_type,
            "title": f"{spec.get('title', 'Gráfico')} · {start + 1}-{end} / {len(labels)}",
            "labels": labels[start:end],
            "series": [
                {**entry, "values": list(entry.get("values", []))[start:end]}
                for entry in spec.get("series", [])
            ],
        })
    return result


def _annex_notice(block: Block) -> str | None:
    if block.kind != "annex" or not block.data.get("truncated"):
        return None
    shown, total = len(block.data.get("rows", [])), block.data.get("total_rows")
    return f"Mostrando {shown} de {total} filas — el resto no se ha omitido en silencio, solo no entra en este documento."


def _chart_of(block: Block) -> dict[str, Any] | None:
    if block.kind == "chart":
        # Bloque de primera clase (sección 10 del Bloque II): los datos y el tipo de gráfico ya los
        # decidió el backend al construir el Document — nunca se re-derivan aquí.
        return block.data
    if block.kind != "table":
        return None
    columns, rows = _rows(block)
    return chart_spec(block.title, columns, rows)


# ------------------------------------------------------------------ Excel
def to_xlsx(doc: Document, generated: datetime, logo: Path | None = None) -> bytes:  # noqa: PLR0915
    logo = resolve_logo(logo)  # Marca SBC obligatoria incluso en llamadas directas al exportador.
    from openpyxl import Workbook  # noqa: PLC0415
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference  # noqa: PLC0415
    from openpyxl.drawing.image import Image  # noqa: PLC0415
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415
    import re  # noqa: PLC0415

    def typed_value(value: Any) -> tuple[Any, str | None]:
        if not isinstance(value, str):
            return value, None
        raw = value.strip()
        eur = re.fullmatch(r"(-?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*€", raw)
        if eur:
            integer = eur.group(2).replace(".", "")
            decimals = (eur.group(3) or "0").ljust(2, "0")
            return float(f"{eur.group(1)}{integer}.{decimals}"), '#,##0.00 "€"'
        pct = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)%", raw)
        if pct:
            return float(pct.group(1).replace(",", ".")) / 100, "0.0%"
        return value, None

    hair = Side(style="thin", color=LINE)
    wb = Workbook()
    wb.remove(wb.active)
    has_explicit_chart = any(b.kind == "chart" for b in doc.blocks)
    for index, block in enumerate(doc.blocks or [Block("section", "Informe", {})], 1):
        raw_title = block.title or f"Hoja {index}"
        for bad_char in r"/\:?*[]":
            raw_title = raw_title.replace(bad_char, "-")
        # 31 es el límite real de Excel para un nombre de hoja (no una cifra arbitraria más corta):
        # truncar antes de eso recortaba títulos que sí cabían (p. ej. "Plantilla por departamento",
        # 26 caracteres, perdía la última letra). El sufijo de desambiguación " (N)" se descuenta de
        # ese mismo límite, nunca de uno más corto.
        base_name = raw_title[:31]
        name = base_name or f"Hoja {index}"
        suffix = 2
        while name in wb.sheetnames:
            tag = f" ({suffix})"
            name = f"{base_name[:31 - len(tag)]}{tag}"
            suffix += 1
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = GOLD if block.kind in ("kpis", "chart") else NAVY
        ws.sheet_view.zoomScale = 90
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.sheet_format.defaultRowHeight = 20
        # Bloque "table"/"annex" con un resumen de indicadores adjunto (``data["kpis"]`` — ver
        # docstring de ``Block``): tarjetas KPI estáticas ANTES de la propia tabla, en la MISMA hoja
        # — nunca una hoja aparte. A diferencia del bloque "kpis" independiente (tarjetas a la
        # derecha de su tabla estrecha Concepto/Valor, con fórmula enlazada), aquí la tabla puede
        # tener muchas columnas (p. ej. detalle diario), así que las tarjetas van ARRIBA, desplazando
        # la fila de cabecera de la tabla hacia abajo, y el valor es fijo (es un agregado calculado
        # aparte, no corresponde a ninguna celda concreta de esta tabla).
        kpi_sidecar = block.data.get("kpis") if isinstance(block.data, dict) else None
        kpi_items = list(kpi_sidecar.items()) if isinstance(kpi_sidecar, dict) and kpi_sidecar else []
        kpi_bands = -(-len(kpi_items) // 3) if kpi_items else 0  # techo: 3 tarjetas por fila
        header_row = 6 + kpi_bands * 5
        for top_row in range(1, 5):
            ws.row_dimensions[top_row].height = 20 if top_row != 2 else 31
            for col in range(1, 15):
                ws.cell(top_row, col).fill = PatternFill("solid", fgColor="FFFFFF" if top_row < 4 else LIGHT)
        ws.row_dimensions[5].height = 9
        ws.row_dimensions[header_row].height = 32
        ws.sheet_properties.outlinePr.summaryBelow = True
        if logo:
            image = Image(str(logo))
            ratio = image.width / max(1, image.height)
            image.height, image.width = 62, 62 * ratio
            ws.add_image(image, "A1")
        ws["C2"] = doc.title
        ws["C2"].font = Font(name="Aptos Display", bold=True, size=20, color=NAVY)
        ws["C2"].alignment = Alignment(vertical="center")
        ws["C3"] = block.title if block.title != doc.title else (doc.subtitle or "")
        ws["C3"].font = Font(name="Aptos", size=11, color=MUTED)
        ws["C4"] = f"SUNSET BEACH CLUB   |   {generated:%d/%m/%Y %H:%M}"
        ws["C4"].font = Font(name="Aptos", bold=True, size=9, color=GOLD)
        if notice := _annex_notice(block):
            ws["C4"] = notice
            ws["C4"].font = Font(size=9, italic=True, color=GOLD)
        for col in range(1, 13):
            ws.cell(row=5, column=col).border = Border(top=Side(style="medium", color=GOLD))
        if kpi_items:
            for idx, (label, value) in enumerate(kpi_items):
                panel_row = 6 + (idx // 3) * 5
                panel_col = 1 + (idx % 3) * 4
                for rr in range(panel_row, panel_row + 4):
                    for cc in range(panel_col, panel_col + 3):
                        ws.cell(rr, cc).fill = PatternFill("solid", fgColor=LIGHT)
                metric = ws.cell(panel_row + 1, panel_col)
                parsed, number_format = typed_value(value)
                metric.value = parsed
                if number_format:
                    metric.number_format = number_format
                elif isinstance(parsed, int | float) and not isinstance(parsed, bool):
                    metric.number_format = "#,##0.##"
                metric.font = Font(name="Aptos Display", size=18, color=NAVY, bold=True)
                metric.alignment = Alignment(vertical="center", horizontal="left", indent=1)
                ws.cell(panel_row + 2, panel_col, str(label)).font = Font(name="Aptos", size=9, color=MUTED)
                ws.row_dimensions[panel_row + 1].height = 30
        columns, rows = _rows(block)
        for c, name in enumerate(columns, 1):
            cell = ws.cell(row=header_row, column=c, value=name)
            cell.font = Font(name="Aptos", bold=True, size=10, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=NAVY)
            cell.alignment = Alignment(wrap_text=True, vertical="center", indent=1)
        severity_col = 1 if block.kind == "warnings" else None
        for r, row in enumerate(rows, header_row + 1):
            for c, value in enumerate(row, 1):
                parsed, number_format = typed_value(value)
                cell = ws.cell(row=r, column=c, value=parsed)
                if number_format:
                    cell.number_format = number_format
                cell.border = Border(bottom=hair)
                cell.font = Font(name="Aptos", size=10, color=NAVY if c == 1 else "293447", bold=(c == 1))
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if c == 1:
                    cell.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
                if severity_col == c:
                    sev = next(
                        (k for k, label in SEVERITY_LABEL.items() if label == value),
                        None,
                    )
                    if sev:
                        cell.font = Font(bold=True, color=SEVERITY_COLOR[sev])
                if (r - header_row) % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor=LIGHT)
                if isinstance(parsed, int | float) and not isinstance(parsed, bool):
                    if not number_format:
                        cell.number_format = "#,##0.##"
                    cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
                    if parsed < 0:
                        cell.font = Font(name="Aptos", size=10, color="B3261E")
        for row_index in range(header_row + 1, header_row + len(rows) + 1):
            original = rows[row_index - header_row - 1]
            visual_lines = 1
            for col_idx, raw in enumerate(original, 1):
                available = max(12, min(56, ws.column_dimensions[get_column_letter(col_idx)].width or 25))
                visual_lines = max(visual_lines, sum(max(1, (len(part) + int(available) - 1) // int(available))
                                                    for part in str(raw if raw is not None else '').split('\n')))
            ws.row_dimensions[row_index].height = min(390, max(24, 16 * visual_lines + 6))
        ws.column_dimensions["A"].width = 18
        for c, name in enumerate(columns, 1):
            width = max([len(str(name))] + [len(str(row[c - 1] or "")) for row in rows[:500] if len(row) >= c]) + 3
            ws.column_dimensions[get_column_letter(c)].width = max(
                ws.column_dimensions[get_column_letter(c)].width or 0, min(max(width, 13), 56)
            )
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
        if rows and columns:
            ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(columns))}{header_row + len(rows)}"
        spec = _chart_of(block) if block.kind == "chart" or not has_explicit_chart else None
        if spec and rows and len(columns) >= 2:
            multi = len(spec.get("series", [])) > 1
            kind = spec.get("type")
            chart: Any = {"donut": PieChart if not multi else BarChart,
                          "line": LineChart, "area": LineChart}.get(kind, BarChart)()
            chart.title = spec["title"]
            # Respetar el subconjunto exacto de columnas numéricas que seleccionó
            # chart_spec(); no incluir accidentalmente identificadores o columnas de texto.
            for selected in spec.get("series", []):
                name = str(selected.get("name", ""))
                if name not in columns[1:]:
                    continue
                col_idx = columns.index(name) + 1
                data = Reference(ws, min_col=col_idx, min_row=header_row, max_row=header_row + len(rows))
                chart.add_data(data, titles_from_data=True)
            cats = Reference(ws, min_col=1, min_row=header_row + 1, max_row=header_row + len(rows))
            chart.set_categories(cats)
            if kind in ("bar", "horizontal_bar") and not multi:
                chart.type = "bar"
                chart.legend = None
            chart.height, chart.width = 10.3, 18.0
            chart.style = 10
            chart.legend = chart.legend if multi or kind == "donut" else None
            for idx, ser in enumerate(chart.series):
                try:
                    ser.graphicalProperties.solidFill = PALETTE[idx % len(PALETTE)]
                    ser.graphicalProperties.line.solidFill = PALETTE[idx % len(PALETTE)]
                except (AttributeError, ValueError):
                    pass
            ws.add_chart(chart, f"{get_column_letter(len(columns) + 2)}{header_row}")
        # Los KPIs se representan como tarjetas vinculadas al bloque real de datos.
        # No se agregan nuevas metricas: cada tarjeta referencia su celda original.
        if block.kind == "kpis" and rows:
            from openpyxl.utils import get_column_letter as _colname  # noqa: PLC0415
            start_col = 5
            ws.column_dimensions["D"].width = 4
            for idx, row in enumerate(rows):
                panel_row = 7 + (idx // 3) * 5
                panel_col = start_col + (idx % 3) * 4
                for rr in range(panel_row, panel_row + 4):
                    for cc in range(panel_col, panel_col + 3):
                        ws.cell(rr, cc).fill = PatternFill("solid", fgColor=LIGHT)
                metric = ws.cell(panel_row + 1, panel_col)
                metric.value = f"=B{header_row + idx + 1}"
                metric.font = Font(name="Aptos Display", size=22, color=NAVY, bold=True)
                metric.alignment = Alignment(vertical="center", horizontal="left", indent=1)
                source_format = ws.cell(header_row + idx + 1, 2).number_format
                if source_format != "General":
                    metric.number_format = source_format
                ws.cell(panel_row + 2, panel_col, str(row[0])).font = Font(name="Aptos", size=9, color=MUTED)
                ws.row_dimensions[panel_row + 1].height = 35
                ws.column_dimensions[_colname(panel_col)].width = max(ws.column_dimensions[_colname(panel_col)].width or 0, 22)
                ws.column_dimensions[_colname(panel_col + 1)].width = max(ws.column_dimensions[_colname(panel_col + 1)].width or 0, 12)
        ws.oddFooter.center.text = f"Sunset Beach Club | {doc.title[:45]}"
        ws.oddFooter.right.text = "Pagina &P / &N"
        ws.print_title_rows = f"1:{header_row}"
        ws.print_options.horizontalCentered = True
        ws.page_margins.left = 0.25
        ws.page_margins.right = 0.25
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
    # Linked KPI cards recalculate when the workbook opens in Excel.
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = 'auto'
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _smart_col_widths(columns: list[str], rows: list[list[Any]], total: float) -> list[float]:
    """Distribute column widths proportionally: text-heavy first column gets more space,
    short numeric columns stay narrow."""
    import re as _re  # noqa: PLC0415

    n = len(columns)
    if n <= 1:
        return [total]
    sample = rows[:80]
    max_lens = [
        max(len(str(columns[c])), max((len(str(r[c])) for r in sample if len(r) > c), default=0))
        for c in range(n)
    ]
    # Numeric-looking columns cap at a shorter max
    for c in range(1, n):
        is_numeric = all(
            _re.match(r"^[\d\s€%/,.\-—]+$", str(r[c])) for r in sample[:20] if len(r) > c and str(r[c]).strip()
        )
        if is_numeric:
            max_lens[c] = min(max_lens[c], 12)
    total_chars = sum(max_lens) or 1
    raw = [total * length / total_chars for length in max_lens]
    # First column minimum 25% of total, max 55%
    raw[0] = max(raw[0], total * 0.25)
    raw[0] = min(raw[0], total * 0.55)
    # Rescale remaining to fill exactly
    rest = total - raw[0]
    rest_sum = sum(raw[1:]) or 1
    raw[1:] = [v * rest / rest_sum for v in raw[1:]]
    return raw


# ------------------------------------------------------------------ PDF
def _pdf_chart(spec: dict[str, Any], width: float) -> Any:
    """Gráfico PDF multiserie: los mismos valores del ChartSpec, sin selección de serie 0."""
    from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart  # noqa: PLC0415
    from reportlab.graphics.charts.linecharts import HorizontalLineChart  # noqa: PLC0415
    from reportlab.graphics.charts.piecharts import Pie  # noqa: PLC0415
    from reportlab.graphics.shapes import Drawing, String  # noqa: PLC0415
    from reportlab.lib import colors  # noqa: PLC0415

    labels = list(spec["labels"])
    series = [s for s in spec["series"] if s.get("values")]
    if not labels or not series:
        return Drawing(width, 1)
    values_by_series = [list(float(v or 0) for v in s["values"]) for s in series]
    hexes = [colors.HexColor(f"#{c}") for c in PALETTE]
    kind = spec.get("type")
    # Un donut de varias series ocultaría todas salvo una: se usa barra agrupada.
    if kind == "donut" and len(series) == 1:
        drawing = Drawing(width, max(150, 24 * len(labels) + 12))
        values = values_by_series[0]
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = 20, 15, 120, 120
        pie.data, pie.labels = values, None
        pie.innerRadiusFraction = 0.55
        for i in range(len(values)):
            pie.slices[i].fillColor = hexes[i % len(hexes)]
            pie.slices[i].strokeColor = colors.white
        drawing.add(pie)
        total = sum(values) or 1
        for i, (label, value) in enumerate(zip(labels, values, strict=True)):
            drawing.add(String(170, drawing.height - 25 - i * 19,
                               f"{str(label)[:30]} : {value:g} ({value / total:.0%})",
                               fontName="Helvetica", fontSize=8.5,
                               fillColor=colors.HexColor(f"#{NAVY}")))
        return drawing
    if kind in ("line", "area"):
        drawing = Drawing(width, 200 if len(series) > 1 else 170)
        line = HorizontalLineChart()
        line.x, line.y, line.width, line.height = 40, 40, width - 70, 115
        line.data = values_by_series
        line.categoryAxis.categoryNames = labels
        line.categoryAxis.labels.fontSize = 8
        line.valueAxis.labels.fontSize = 8
        for i, data_series in enumerate(series):
            line.lines[i].strokeColor = hexes[i % len(hexes)]
            line.lines[i].strokeWidth = 2
            if len(series) > 1:
                drawing.add(String(35 + i * min(150, width / max(1, len(series))),
                                   174, str(data_series.get("name", f"Serie {i + 1}"))[:24],
                                   fontName="Helvetica", fontSize=9, fillColor=hexes[i % len(hexes)]))
        drawing.add(line)
        return drawing
    horizontal = len(labels) > 6
    height = max(160, (18 * len(labels) + 40) if horizontal else 180)
    drawing = Drawing(width, height)
    bars = HorizontalBarChart() if horizontal else VerticalBarChart()
    bars.x, bars.y = (120, 22) if horizontal else (45, 23)
    bars.width, bars.height = (width - 175, height - 60) if horizontal else (width - 80, height - 67)
    bars.data = [list(reversed(s)) if horizontal else s for s in values_by_series]
    bars.categoryAxis.categoryNames = list(reversed(labels)) if horizontal else labels
    bars.categoryAxis.labels.fontSize = 8
    bars.valueAxis.labels.fontSize = 8
    bars.valueAxis.valueMin = min(0, min(v for data in values_by_series for v in data))
    for i in range(len(series)):
        bars.bars[i].fillColor = hexes[i % len(hexes)]
        bars.bars[i].strokeColor = None
    # Etiquetas de series en lugar de etiquetar cada barra, para no solaparlas.
    if len(series) > 1:
        for i, data_series in enumerate(series):
            drawing.add(String(45 + i * min(150, width / max(1, len(series))), height - 14,
                               str(data_series.get("name", f"Serie {i + 1}"))[:24],
                               fontName="Helvetica", fontSize=9, fillColor=hexes[i % len(hexes)]))
    else:
        bars.barLabelFormat = "%g"
        bars.barLabels.fontSize = 8
        bars.barLabels.nudge = 8
    drawing.add(bars)
    return drawing


def to_pdf(doc: Document, generated: datetime, logo: Path | None = None) -> bytes:  # noqa: PLR0915
    from reportlab.lib import colors  # noqa: PLC0415
    logo = resolve_logo(logo)  # Marca SBC obligatoria incluso en llamadas directas al exportador.
    from reportlab.lib.pagesizes import A4, landscape  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import cm  # noqa: PLC0415
    from reportlab.lib.utils import ImageReader  # noqa: PLC0415
    from reportlab.pdfbase import pdfmetrics  # noqa: PLC0415
    from reportlab.pdfbase.ttfonts import TTFont  # noqa: PLC0415
    font_regular, font_bold, font_italic = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
    font_dir = Path("/usr/share/fonts/truetype/lato")
    if all((font_dir / f).exists() for f in ("Lato-Regular.ttf", "Lato-Bold.ttf", "Lato-Italic.ttf")):
        for key, filename in (("SBC-Lato", "Lato-Regular.ttf"), ("SBC-Lato-Bold", "Lato-Bold.ttf"),
                              ("SBC-Lato-Italic", "Lato-Italic.ttf")):
            if key not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(key, str(font_dir / filename)))
        font_regular, font_bold, font_italic = "SBC-Lato", "SBC-Lato-Bold", "SBC-Lato-Italic"
    from reportlab.platypus import (  # noqa: PLC0415
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    hexc = lambda h: colors.HexColor(f"#{h}")  # noqa: E731
    widest = max((len(_rows(b)[0]) for b in doc.blocks if b.kind == "table"), default=2)
    page = landscape(A4) if widest > 4 else A4
    margin = 1.6 * cm
    logo_h = 1.5 * cm
    logo_w = 0.0
    if logo:
        iw, ih = ImageReader(str(logo)).getSize()
        logo_w = logo_h * iw / ih

    def decorate(canvas: Any, pdf_doc: Any) -> None:
        canvas.saveState()
        if logo:
            canvas.drawImage(
                str(logo),
                margin,
                page[1] - margin - logo_h + 0.2 * cm,
                width=logo_w,
                height=logo_h,
                mask="auto",
                preserveAspectRatio=True,
            )
        canvas.setFont(font_bold, 8)
        canvas.setFillColor(hexc(NAVY))
        canvas.drawRightString(page[0] - margin, page[1] - margin - 0.24 * cm, "SUNSET BEACH CLUB  /  REPORTING")
        canvas.setStrokeColor(hexc(GOLD))
        canvas.setLineWidth(1.2)
        y = page[1] - margin - logo_h - 0.05 * cm
        canvas.line(margin, y, page[0] - margin, y)
        canvas.setStrokeColor(hexc(LINE))
        canvas.setLineWidth(0.5)
        canvas.line(margin, margin - 0.25 * cm, page[0] - margin, margin - 0.25 * cm)
        canvas.setFont(font_regular, 8)
        canvas.drawString(margin, margin - 0.65 * cm, f"SUNSET BEACH CLUB   |   {generated:%d/%m/%Y}")
        canvas.setFillColor(hexc(MUTED))
        canvas.drawRightString(page[0] - margin, margin - 0.65 * cm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin + logo_h + 0.6 * cm,
        bottomMargin=margin + 0.3 * cm,
        title=doc.title,
        author="Sunset Beach Club",
    )
    title_style = ParagraphStyle(
        "t", fontName=font_bold, fontSize=24, leading=29, textColor=hexc(NAVY), spaceAfter=7
    )
    sub_style = ParagraphStyle("s", fontName=font_regular, fontSize=11, leading=15, textColor=hexc(MUTED))
    h2 = ParagraphStyle("h2", fontName=font_bold, fontSize=13, leading=17, textColor=hexc(NAVY))
    cell = ParagraphStyle("c", fontName=font_regular, fontSize=8.7, leading=12, textColor=hexc("222222"))
    head = ParagraphStyle("h", parent=cell, fontName=font_bold, textColor=colors.white)
    label_style = ParagraphStyle("l", parent=cell, fontName=font_bold, textColor=hexc(MUTED), fontSize=8)
    value_style = ParagraphStyle("v", parent=cell, fontSize=10, leading=14)
    kpi_value = ParagraphStyle(
        "kv", fontName=font_bold, fontSize=18, leading=23, textColor=hexc(NAVY), alignment=1
    )
    kpi_label = ParagraphStyle("kl", fontName=font_regular, fontSize=8, leading=11, textColor=hexc(MUTED), alignment=1)
    evidence_style = ParagraphStyle("ev", parent=cell, fontSize=7.5, fontName=font_italic, textColor=hexc(MUTED))
    annex_notice_style = ParagraphStyle("an", parent=cell, fontSize=8.5, fontName=font_italic, textColor=hexc(GOLD))
    severity_label_styles = {
        sev: ParagraphStyle(f"warnlbl_{sev}", parent=cell, fontName=font_bold, fontSize=9, textColor=hexc(color))
        for sev, color in SEVERITY_COLOR.items()
    }

    def para(value: Any, style: Any) -> Paragraph:
        text = "" if value is None else str(value)
        return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)

    width = page[0] - 2 * margin

    def heading(text: str) -> Table:
        bar = Table([[para(text, h2)]], colWidths=[width - 0.35 * cm])
        wrapper = Table([["", bar]], colWidths=[0.2 * cm, width - 0.2 * cm])
        wrapper.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), hexc(GOLD)),
                    ("LEFTPADDING", (1, 0), (1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        return wrapper

    def kpi_grid(items: list[tuple[str, Any]]) -> Table:
        # 5 per row when there are many KPIs (executive reports); else 4.
        per_row = 4 if len(items) > 8 else min(3, max(1, len(items)))
        kpi_w = (width - 0.48 * cm * per_row) / per_row
        cards = [
            [
                Table([[para(v, kpi_value)], [para(k, kpi_label)]], colWidths=[kpi_w])
                for k, v in items[i : i + per_row]
            ]
            for i in range(0, len(items), per_row)
        ]
        cards = [[*card_row, *([""] * (per_row - len(card_row)))] for card_row in cards]
        grid = Table(cards, colWidths=[width / per_row] * per_row)
        grid.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        for row_index in range(len(cards)):
            for col_index in range(per_row):
                if cards[row_index][col_index] != "":
                    grid.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (col_index, row_index), (col_index, row_index), hexc(LIGHT)),
                                ("BOX", (col_index, row_index), (col_index, row_index), 0.8, hexc(LINE)),
                                ("TOPPADDING", (col_index, row_index), (col_index, row_index), 8),
                                ("BOTTOMPADDING", (col_index, row_index), (col_index, row_index), 8),
                            ]
                        )
                    )
        return grid

    eyebrow = ParagraphStyle("brand_eyebrow", fontName=font_bold, fontSize=8, leading=11,
                             textColor=hexc(GOLD), spaceAfter=6)
    story: list[Any] = [para("ANÁLISIS CORPORATIVO   /   INFORME", eyebrow), para(doc.title, title_style)]
    meta = "  ·  ".join(x for x in [doc.subtitle, *doc.badges] if x)
    if meta:
        story.append(para(meta, sub_style))
    story.append(Spacer(1, 0.5 * cm))
    has_explicit_chart = any(b.kind == "chart" for b in doc.blocks)
    for block in doc.blocks:
        columns, rows = _rows(block)
        if not rows:
            continue
        same_title = block.title == doc.title
        parts: list[Any] = [Spacer(1, 0.05 * cm) if same_title else heading(block.title), Spacer(1, 0.25 * cm)]
        if block.kind == "kpis":
            parts.append(kpi_grid(list(block.data.items())))
        elif block.kind == "section":
            pairs = Table(
                [[para(k, label_style), para(v, value_style)] for k, v in block.data.items()],
                colWidths=[width * 0.32, width * 0.68],
            )
            pairs.setStyle(
                TableStyle(
                    [
                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, hexc(LINE)),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            parts.append(pairs)
        elif block.kind == "chart":
            # El detalle tabular va en su bloque específico; repetirlo aquí
            # estaba ocupando páginas sin aportar información nueva.
            for chart_segment in _chart_segments(block.data):
                parts.append(_pdf_chart(chart_segment, width))
        elif block.kind == "warnings":
            cells = []
            for item in block.data.get("items", []):
                sev = item.get("severity", "info")
                label = f"{SEVERITY_LABEL.get(sev, sev.upper())} · {item.get('code', '')}"
                style = severity_label_styles.get(sev, label_style)
                cells.append([[para(label, style), para(item.get("message", ""), value_style)]])
            grid = Table(cells, colWidths=[width])
            grid.setStyle(
                TableStyle(
                    [
                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, hexc(LINE)),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            parts.append(grid)
        elif block.kind == "narrative":
            cells = []
            for s in block.data.get("statements", []):
                kind_label = NARRATIVE_LABEL.get(s.get("kind"), str(s.get("kind", "")).upper())
                flow = [para(kind_label, label_style), para(s.get("text", ""), value_style)]
                evidence = s.get("evidence") or {}
                if evidence:
                    flow.append(para(f"Evidencia: {_flat_evidence(evidence)}", evidence_style))
                cells.append([flow])
            grid = Table(cells, colWidths=[width])
            grid.setStyle(
                TableStyle(
                    [
                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, hexc(LINE)),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            parts.append(grid)
        else:
            # Bloque "table"/"annex" con un resumen de indicadores adjunto (``data["kpis"]``, p. ej.
            # un informe con una entidad por bloque — persona, proyecto…): tarjetas KPI justo encima
            # de su propia tabla, bajo el MISMO título — nunca un bloque "kpis" aparte, que en Excel/
            # PowerPoint se convertiría en una pestaña/diapositiva propia para lo que es un resumen de
            # ESTA tabla, no una sección independiente.
            if isinstance(block.data, dict) and isinstance(block.data.get("kpis"), dict) and block.data["kpis"]:
                parts += [kpi_grid(list(block.data["kpis"].items())), Spacer(1, 0.3 * cm)]
            if notice := _annex_notice(block):
                parts += [para(notice, annex_notice_style), Spacer(1, 0.15 * cm)]
            if not has_explicit_chart and (spec := _chart_of(block)):
                for chart_segment in _chart_segments(spec):
                    parts += [_pdf_chart(chart_segment, width), Spacer(1, 0.2 * cm)]
            col_widths = _smart_col_widths(columns, rows, width)
            first_col_style = ParagraphStyle("fc", parent=cell, fontName=font_bold, textColor=hexc(NAVY))

            def _data_row(row: list[Any]) -> list[Any]:
                return [para(v, first_col_style if i == 0 else cell) for i, v in enumerate(row)]

            grid = Table(
                [[para(c, head) for c in columns]] + [_data_row(row) for row in rows],
                colWidths=col_widths,
                repeatRows=1,
            )
            grid.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), hexc(NAVY)),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, hexc(LIGHT)]),
                        ("LINEBELOW", (0, 1), (-1, -1), 0.3, hexc(LINE)),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("LINEAFTER", (0, 0), (0, -1), 0.5, hexc(LINE)),
                    ]
                )
            )
            parts.append(grid)
        story += [KeepTogether(parts[:2] + parts[2:3]), *parts[3:], Spacer(1, 0.55 * cm)]
    pdf.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# ------------------------------------------------------------------ PowerPoint
def to_pptx(doc: Document, generated: datetime, logo: Path | None = None) -> bytes:  # noqa: PLR0915
    """Premium 16:9 deck, keeping the original Document/Block engine and editable charts."""
    logo = resolve_logo(logo)
    from pptx import Presentation  # noqa: PLC0415
    from pptx.dml.color import RGBColor  # noqa: PLC0415
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR  # noqa: PLC0415
    from pptx.util import Inches, Pt  # noqa: PLC0415

    navy, gold, muted = (RGBColor.from_string(c) for c in (NAVY, GOLD, MUTED))
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.3333333333), Inches(7.5)
    blank = prs.slide_layouts[6]
    counter = {"n": 0}

    def text(slide: Any, value: Any, x: float, y: float, w: float, h: float, size: int,
             color: Any, bold: bool = False, align: Any = PP_ALIGN.LEFT) -> Any:
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = shape.text_frame
        frame.clear()
        frame.word_wrap = True
        frame.margin_left = Inches(0.02)
        frame.margin_right = Inches(0.02)
        frame.margin_top = Inches(0.02)
        frame.margin_bottom = Inches(0.02)
        para = frame.paragraphs[0]
        para.text = str(value)
        para.alignment = align
        para.font.name = "Aptos Display" if bold else "Aptos"
        para.font.size = Pt(size)
        para.font.bold = bold
        para.font.color.rgb = color
        return shape

    def header(slide: Any, value: str) -> None:
        counter["n"] += 1
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(255, 255, 255)
        slide.shapes.add_picture(str(logo), Inches(0.48), Inches(0.12), height=Inches(0.78))
        text(slide, "SUNSET BEACH CLUB  /  INFORMES", 9.30, 0.31, 3.44, 0.29, 10, muted, True, PP_ALIGN.RIGHT)
        band = slide.shapes.add_shape(1, Inches(0.45), Inches(1.01), Inches(12.40), Inches(0.035))
        band.fill.solid()
        band.fill.fore_color.rgb = gold
        band.line.fill.background()
        title_len = len(str(value))
        text(slide, value, 0.53, 1.10, 12.10, 0.49 if title_len < 80 else 0.68,
             23 if title_len < 74 else 17, navy, True)
        bottom = slide.shapes.add_shape(1, Inches(0.5), Inches(7.09), Inches(12.3), Inches(0.008))
        bottom.fill.solid()
        bottom.fill.fore_color.rgb = RGBColor.from_string(LINE)
        bottom.line.fill.background()
        text(slide, f"Sunset Beach Club   ·   {generated:%d/%m/%Y}", 0.53, 7.12, 8.0, 0.20, 9, muted)
        text(slide, f"{counter['n']:02d}", 12.2, 7.12, 0.60, 0.20, 9, muted, False, PP_ALIGN.RIGHT)

    cover = prs.slides.add_slide(blank)
    counter["n"] += 1
    cover.background.fill.solid()
    cover.background.fill.fore_color.rgb = navy
    # The logo is legible on the white top panel, including the cover.
    top = cover.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.3333), Inches(1.18))
    top.fill.solid()
    top.fill.fore_color.rgb = RGBColor(255, 255, 255)
    top.line.fill.background()
    cover.shapes.add_picture(str(logo), Inches(0.52), Inches(0.12), height=Inches(0.84))
    text(cover, "SUNSET BEACH CLUB    /    INFORME EJECUTIVO", 8.2, 0.48, 4.6, 0.30, 10, navy, True, PP_ALIGN.RIGHT)
    accent = cover.shapes.add_shape(1, Inches(0.77), Inches(2.12), Inches(0.09), Inches(2.9))
    accent.fill.solid()
    accent.fill.fore_color.rgb = gold
    accent.line.fill.background()
    title_size = 37 if len(doc.title) < 68 else (31 if len(doc.title) < 120 else 24)
    text(cover, doc.title, 1.18, 2.05, 10.85, 2.4, title_size,
         RGBColor(255, 255, 255), True)
    if doc.subtitle:
        text(cover, doc.subtitle, 1.20, 4.91, 10.8, 0.88, 18,
             RGBColor.from_string("DDE3F3"))
    separator = cover.shapes.add_shape(1, Inches(1.2), Inches(6.69), Inches(10.9), Inches(0.02))
    separator.fill.solid()
    separator.fill.fore_color.rgb = gold
    separator.line.fill.background()
    text(cover, f"DOCUMENTO CORPORATIVO   ·   {generated:%d/%m/%Y}",
         1.20, 6.83, 10.8, 0.3, 10, RGBColor.from_string("DDE3F3"), True)

    has_explicit_chart = any(b.kind == "chart" for b in doc.blocks)
    has_detail = any(b.kind in ("table", "annex") for b in doc.blocks)
    for block in doc.blocks:
        if block.kind == "kpis":
            _kpi_slide(prs, blank, header, block)
            continue
        if block.kind == "warnings":
            _warnings_slide(prs, blank, header, block)
            continue
        if block.kind == "chart" or not has_explicit_chart:
            if spec := _chart_of(block):
                _chart_slide(prs, blank, header, block.title, spec)
        if block.kind == "chart" and has_detail:
            continue
        sidecar_kpis = block.data.get("kpis") if isinstance(block.data, dict) else None
        if block.kind in ("table", "annex") and isinstance(sidecar_kpis, dict) and sidecar_kpis:
            # Mismo bloque, dos diapositivas consecutivas con el MISMO título — resumen y detalle de
            # la misma entidad, nunca dos entidades distintas (ver sidecar "kpis" en to_pdf/to_xlsx).
            _kpi_slide(prs, blank, header, Block("kpis", block.title, sidecar_kpis))
        _table_slides(prs, blank, header, block)
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _chart_slide(prs: Any, layout: Any, header: Any, title: str, spec: dict[str, Any]) -> None:
    from pptx.chart.data import CategoryChartData  # noqa: PLC0415
    from pptx.dml.color import RGBColor  # noqa: PLC0415
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION  # noqa: PLC0415
    from pptx.util import Inches, Pt  # noqa: PLC0415

    segmented = _chart_segments(spec, 13)
    if len(segmented) > 1:
        for segment in segmented:
            _chart_slide(prs, layout, header, segment["title"], segment)
        return
    slide = prs.slides.add_slide(layout)
    header(slide, title)
    data = CategoryChartData()
    data.categories = spec["labels"]
    for index, entry in enumerate(spec["series"]):
        data.add_series(str(entry.get("name") or f"Serie {index + 1}"), entry["values"])
    multi = len(spec["series"]) > 1
    kind = {"donut": XL_CHART_TYPE.DOUGHNUT if not multi else XL_CHART_TYPE.COLUMN_CLUSTERED,
            "line": XL_CHART_TYPE.LINE_MARKERS,
            "area": XL_CHART_TYPE.LINE_MARKERS}.get(spec["type"], XL_CHART_TYPE.BAR_CLUSTERED)
    chart = slide.shapes.add_chart(kind, Inches(0.71), Inches(1.89), Inches(11.86), Inches(4.93), data).chart
    chart.chart_style = 10
    chart.has_legend = multi or spec["type"] == "donut"
    if chart.has_legend:
        chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
        chart.legend.font.size = Pt(11)
    plot = chart.plots[0]
    plot.has_data_labels = len(spec.get("labels", [])) <= 8 and not (multi and len(spec.get("labels", [])) > 5)
    if spec["type"] != "donut":
        for idx, series in enumerate(plot.series):
            if spec["type"] not in ("line", "area"):
                series.format.fill.solid()
                series.format.fill.fore_color.rgb = RGBColor.from_string(PALETTE[idx % len(PALETTE)])
            else:
                series.format.line.color.rgb = RGBColor.from_string(PALETTE[idx % len(PALETTE)])
        if spec["type"] == "bar":
            chart.category_axis.reverse_order = True


def _kpi_slide(prs: Any, layout: Any, header: Any, block: Block) -> None:
    from pptx.dml.color import RGBColor  # noqa: PLC0415
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR  # noqa: PLC0415
    from pptx.util import Inches, Pt  # noqa: PLC0415

    navy = RGBColor.from_string(NAVY)
    items = list(block.data.items())
    if not items:
        return
    for start in range(0, len(items), 12):
        page_items = items[start:start + 12]
        slide = prs.slides.add_slide(layout)
        header(slide, block.title if start == 0 else f"{block.title} (cont.)")
        count = len(page_items)
        cols = min(4, count) if count > 3 else count
        rows = (count + cols - 1) // cols
        gap_x, gap_y = 0.18, 0.22
        avail_w, avail_h = 12.12, 4.86
        cw = (avail_w - (cols - 1) * gap_x) / cols
        ch = min(2.50 if rows == 1 else 2.15, (avail_h - (rows - 1) * gap_y) / rows)
        y0 = 1.76 + max(0, (4.86 - rows * ch - (rows - 1) * gap_y) / 2)
        for i, (label, value) in enumerate(page_items):
            x = 0.60 + (i % cols) * (cw + gap_x)
            y = y0 + (i // cols) * (ch + gap_y)
            panel = slide.shapes.add_shape(5, Inches(x), Inches(y), Inches(cw), Inches(ch))
            panel.fill.solid()
            panel.fill.fore_color.rgb = RGBColor.from_string(LIGHT)
            panel.line.color.rgb = RGBColor.from_string(LINE)
            stripe = slide.shapes.add_shape(1, Inches(x + 0.20), Inches(y + 0.24), Inches(0.36), Inches(0.055))
            stripe.fill.solid()
            stripe.fill.fore_color.rgb = RGBColor.from_string(GOLD)
            stripe.line.fill.background()
            frame = slide.shapes.add_textbox(Inches(x + 0.20), Inches(y + 0.43),
                                             Inches(cw - 0.38), Inches(ch - 0.56)).text_frame
            frame.word_wrap = True
            frame.margin_left = 0
            frame.margin_top = 0
            para = frame.paragraphs[0]
            para.text = str(value)
            para.font.name = "Aptos Display"
            para.font.size = Pt(29 if len(str(value)) < 13 else (22 if len(str(value)) < 19 else 15))
            para.font.bold = True
            para.font.color.rgb = navy
            sub = frame.add_paragraph()
            sub.text = str(label)
            sub.space_before = Pt(9)
            sub.font.name = "Aptos"
            sub.font.size = Pt(12 if len(str(label)) < 32 else 10)
            sub.font.color.rgb = RGBColor.from_string(MUTED)


def _warnings_slide(prs: Any, layout: Any, header: Any, block: Block) -> None:
    """Diapositiva dedicada (no una tabla genérica): cada advertencia con su severidad en color,
    condición obligatoria 2 de la aprobación de Fase D."""
    from pptx.dml.color import RGBColor  # noqa: PLC0415
    from pptx.util import Inches, Pt  # noqa: PLC0415

    items = block.data.get("items", [])
    for start in range(0, max(len(items), 1), 5):
        chunk = items[start : start + 5]
        slide = prs.slides.add_slide(layout)
        header(slide, block.title if start == 0 else f"{block.title} (cont.)")
        count = max(1, len(chunk))
        row_h = min(1.20 if count > 1 else 2.38, (4.70 - (count - 1) * .20) / count)
        top = 1.85 + (4.70 - (row_h * count + (count - 1) * .20)) / 2
        for i, item in enumerate(chunk):
            sev = item.get("severity", "info")
            y = Inches(top + i * (row_h + .20))
            panel = slide.shapes.add_shape(5, Inches(0.60), y, Inches(12.10), Inches(row_h))
            panel.fill.solid()
            panel.fill.fore_color.rgb = RGBColor.from_string(LIGHT)
            panel.line.color.rgb = RGBColor.from_string(LINE)
            box = slide.shapes.add_textbox(Inches(0.91), y + Inches(0.20),
                                           Inches(11.5), Inches(row_h - .28)).text_frame
            box.word_wrap = True
            box.text = f"{SEVERITY_LABEL.get(sev, sev.upper())} · {item.get('code', '')}"
            box.paragraphs[0].runs[0].font.size = Pt(15)
            box.paragraphs[0].runs[0].font.bold = True
            box.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string(SEVERITY_COLOR.get(sev, MUTED))
            msg = box.add_paragraph()
            msg.text = str(item.get("message", ""))
            msg.runs[0].font.size = Pt(16 if len(chunk) == 1 else 12)
            msg.runs[0].font.color.rgb = RGBColor(0x22, 0x22, 0x22)


def _table_slides(prs: Any, layout: Any, header: Any, block: Block) -> None:
    from pptx.dml.color import RGBColor  # noqa: PLC0415
    from pptx.util import Inches, Pt  # noqa: PLC0415

    columns, original_rows = _rows(block)
    if not columns or not original_rows:
        return
    notice = _annex_notice(block)
    # No se elimina texto: una celda larga se divide en fragmentos de continuación.
    # El contenido concatenado de esos fragmentos coincide con el valor original.
    import math  # noqa: PLC0415
    ncols = len(columns)
    per_cell = max(30, min(100, 290 // ncols))
    expanded = []
    for original in original_rows:
        values = ["" if c >= len(original) or original[c] is None else str(original[c]) for c in range(ncols)]
        segments = max(1, max(math.ceil(len(v) / per_cell) for v in values))
        for j in range(segments):
            expanded.append([v[j * per_cell : (j + 1) * per_cell] for v in values])
    compact = ncols <= 5 and all(len(str(v)) <= 35 for row in expanded for v in row)
    rows_per_page = 9 if compact else 6
    for start in range(0, len(expanded), rows_per_page):
        chunk = expanded[start : start + rows_per_page]
        slide = prs.slides.add_slide(layout)
        title = block.title if start == 0 else f"{block.title} (cont.)"
        header(slide, f"{title} · {notice}" if notice and start == 0 else title)
        row_height = min(0.86, 4.75 / (len(chunk) + 1))
        total_height = row_height * (len(chunk) + 1)
        table_y = 1.95 + max(0.0, (4.75 - total_height) / 2)
        shape = slide.shapes.add_table(
            len(chunk) + 1, len(columns), Inches(0.50), Inches(table_y),
            Inches(12.3), Inches(total_height)
        )
        grid = shape.table
        from pptx.enum.text import MSO_ANCHOR  # noqa: PLC0415
        # The first, descriptive field has additional width; numeric columns remain compact.
        if ncols > 1:
            header_lens = [len(str(v)) for v in columns]
            descriptive = max((len(str(row[0])) for row in chunk), default=0)
            left_w = min(5.5, max(2.4, (max(descriptive, header_lens[0]) / 36.0) * 4.5))
            grid.columns[0].width = Inches(left_w)
            rest_w = (12.3 - left_w) / (ncols - 1)
            for c in range(1, ncols):
                grid.columns[c].width = Inches(rest_w)
        for c, name in enumerate(columns):
            grid.cell(0, c).text = str(name)
            grid.cell(0, c).vertical_anchor = MSO_ANCHOR.MIDDLE
            grid.cell(0, c).margin_left = Inches(.14)
            grid.cell(0, c).fill.solid()
            grid.cell(0, c).fill.fore_color.rgb = RGBColor.from_string(NAVY)
        for r, row in enumerate(chunk, 1):
            for c, value in enumerate(row):
                cell = grid.cell(r, c)
                cell.text = value
                cell.text_frame.word_wrap = True
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.margin_left = Inches(.14)
                cell.margin_right = Inches(.12)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(LIGHT if r % 2 == 0 else "FFFFFF")
        for r in range(len(chunk) + 1):
            for c in range(len(columns)):
                for paragraph in grid.cell(r, c).text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = "Aptos"
                        run.font.size = Pt(12 if r == 0 else (10 if ncols > 5 else 13))
                        run.font.color.rgb = RGBColor(255, 255, 255) if r == 0 else RGBColor(0x22, 0x22, 0x22)
                        run.font.bold = r == 0



RENDERERS = {"pdf": to_pdf, "xlsx": to_xlsx, "pptx": to_pptx, "html": to_html, "docx": to_docx}
