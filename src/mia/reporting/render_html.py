"""Renderizador HTML del motor documental universal (Bloque II, Fase E).

Mismo contrato que PDF/XLSX/PPTX/DOCX (``Document``/``Block`` de ``document.py``): nunca recalcula ninguna
cifra, solo pinta lo que ya decidió el backend. Autocontenido (sin CSS/JS externos, logo incrustado en
base64) para que un informe HTML se pueda abrir o archivar sin depender de ninguna ruta externa —
mismo motivo por el que el logotipo SBC se incrusta y nunca se referencia por URL.

Gráficos: SVG generado en el propio servidor (sin ninguna librería de JavaScript ni CDN) a partir de la
MISMA especificación ``{type, title, labels, series}`` que ya consumen PDF/XLSX/PPTX/DOCX
(``mia.reporting.charts``) — ni un motor de gráficos paralelo ni una re-derivación.

Seguridad: todo texto que proviene de datos (títulos, celdas, mensajes de advertencia, afirmaciones
narrativas) pasa por ``_esc()`` antes de insertarse — nunca se interpola en crudo. Ver
``tests/test_reports_render_html.py`` para la prueba explícita de inyección.
"""

from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path
from typing import Any

from mia.assets import resolve_logo
from mia.reporting.charts import chart_spec
from mia.reporting.document import Block, Document

NAVY = "#1B2559"
GOLD = "#D8A565"
LIGHT = "#F6F3EE"
LINE = "#E3DDD3"
MUTED = "#6B6F80"
PALETTE = ["#1B2559", "#D8A565", "#3A8F8A", "#D9776B", "#5B8DEF", "#8A6BB0", "#7FA37A", "#C9B8A3"]

SEVERITY_COLOR = {"blocker": "#B3261E", "data_quality": "#A66A1E", "info": "#3A8F8A"}
SEVERITY_LABEL = {"blocker": "BLOQUEANTE", "data_quality": "CALIDAD DE DATOS", "info": "INFO"}
NARRATIVE_LABEL = {
    "fact": "HECHO VERIFICADO", "interpretation": "INTERPRETACIÓN",
    "hypothesis": "HIPÓTESIS", "recommendation": "RECOMENDACIÓN",
}


def _esc(value: Any) -> str:
    """Escapa cualquier valor antes de insertarlo en el HTML — nunca texto sin escapar, aunque el
    propio backend ya lo considere «de confianza» (defensa en profundidad, sección 14: «seguridad
    frente a contenido HTML no confiable»)."""
    return html.escape("" if value is None else str(value), quote=True)


def _logo_data_uri(logo: Path | None) -> str | None:
    if not logo or not logo.exists():
        return None
    encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
    ext = logo.suffix.lstrip(".").lower() or "png"
    mime = {"jpg": "jpeg"}.get(ext, ext)
    return f"data:image/{mime};base64,{encoded}"


# ------------------------------------------------------------------ gráficos SVG (sin JS, sin CDN)
def _svg_bar(spec: dict[str, Any], *, horizontal: bool = False) -> str:
    labels = spec["labels"]
    series = spec.get("series", [])
    if not series:
        return ""
    n = len(series)
    row_h = max(38, 18 + 20 * n)
    width, height = 650, 42 + row_h * len(labels)
    values = [float(v or 0) for s in series for v in s["values"]]
    vmax = max([1.0, *[abs(v) for v in values]])
    has_negative = any(v < 0 for v in values)
    zero_x = 330 if has_negative else 152
    positive_width, negative_width = (210, 170) if has_negative else (340, 0)
    bars = []
    if has_negative:
        bars.append(f'<line x1="{zero_x}" x2="{zero_x}" y1="3" y2="{height-10}" stroke="{LINE}" stroke-width="1.5" />')
    for i, label in enumerate(labels):
        y = 16 + i * row_h
        bars.append(f'<text x="0" y="{y + 12}" font-size="11" fill="{MUTED}">{_esc(str(label)[:22])}</text>')
        for j, s in enumerate(series):
            value = float(s["values"][i] or 0)
            bar_w = max(1.0, abs(value) / vmax * (negative_width if value < 0 else positive_width))
            bar_y = y + 16 + j * 19
            bar_x = zero_x - bar_w if value < 0 else zero_x
            label_x = bar_x - 6 if value < 0 else bar_x + bar_w + 8
            anchor = "end" if value < 0 else "start"
            bars.append(
                f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w:.1f}" height="14" rx="2" fill="{PALETTE[j % len(PALETTE)]}" />'
                f'<text x="{label_x:.1f}" y="{bar_y + 11}" font-size="10" text-anchor="{anchor}" fill="{NAVY}">{_esc(round(value, 2))}</text>'
            )
    if n > 1:
        legend = " ".join(
            f'<span class="legend-dot" style="background:{PALETTE[j % len(PALETTE)]}"></span>{_esc(str(s.get("name", f"Serie {j+1}")))}'
            for j, s in enumerate(series)
        )
        bars.append(f'<foreignObject x="0" y="{height - 5}" width="650" height="1"></foreignObject>')
        return f'<div><div class="legend">{legend}</div><svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(spec.get("title"))}">' + "".join(bars) + "</svg></div>"
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(spec.get("title"))}">' + "".join(bars) + "</svg>"


def _svg_donut(spec: dict[str, Any]) -> str:
    labels = spec["labels"]
    series = spec["series"][:1]
    values = [max(0.0, v or 0.0) for v in series[0]["values"]] if series else []
    total = sum(values) or 1.0
    size, r, cx, cy = 220, 70, 110, 90
    circumference = 2 * 3.14159265 * r
    offset = 0.0
    segments = []
    legend = []
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        frac = value / total
        length = frac * circumference
        color = PALETTE[i % len(PALETTE)]
        segments.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="28" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})" />'
        )
        legend.append(
            f'<span class="legend-dot" style="background:{color}"></span>{_esc(label)} '
            f'<strong>{round(frac * 100, 1)}%</strong>'
        )
        offset += length
    svg = f'<svg viewBox="0 0 {size} {size}" width="220" height="220" role="img" aria-label="{_esc(spec.get("title"))}">' + "".join(segments) + "</svg>"
    return f'<div class="donut-wrap">{svg}<div class="legend">{"<br/>".join(legend)}</div></div>'


def _svg_line(spec: dict[str, Any], *, area: bool = False) -> str:
    labels = spec["labels"]
    series = spec["series"]
    width, height, pad = 560, 220, 30
    all_values = [v or 0.0 for s in series for v in s["values"]]
    if not all_values or len(labels) < 2:
        return ""
    vmax, vmin = max(all_values), min(0.0, min(all_values))
    span = (vmax - vmin) or 1.0
    step = (width - 2 * pad) / (len(labels) - 1)

    def points(values: list[float]) -> list[tuple[float, float]]:
        return [
            (pad + i * step, height - pad - ((v or 0.0) - vmin) / span * (height - 2 * pad))
            for i, v in enumerate(values)
        ]

    parts = [f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="{LINE}" />']
    for i, s in enumerate(series):
        color = PALETTE[i % len(PALETTE)]
        pts = points(s["values"])
        path = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(pts))
        if area:
            floor_y = height - pad
            path += f" L{pts[-1][0]:.1f},{floor_y} L{pts[0][0]:.1f},{floor_y} Z"
            parts.append(f'<path d="{path}" fill="{color}" opacity="0.18" stroke="none" />')
            path = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(pts))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" />')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}" />')
    for i, label in enumerate(labels):
        x = pad + i * step
        parts.append(f'<text x="{x:.1f}" y="{height - 8}" font-size="10" fill="{MUTED}" text-anchor="middle">{_esc(label)[:10]}</text>')
    svg = f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(spec.get("title"))}">' + "".join(parts) + "</svg>"
    if len(series) > 1:
        legend = " ".join(
            f'<span class="legend-dot" style="background:{PALETTE[i % len(PALETTE)]}"></span>{_esc(str(s.get("name", f"Serie {i + 1}")))}'
            for i, s in enumerate(series)
        )
        return f'<div><div class="legend">{legend}</div>{svg}</div>'
    return svg


def _chart_svg(spec: dict[str, Any]) -> str:
    kind = spec.get("type")
    if kind == "donut" and len(spec.get("series", [])) == 1:
        return _svg_donut(spec)
    if kind in ("line",):
        return _svg_line(spec, area=False)
    if kind == "area":
        return _svg_line(spec, area=True)
    if kind == "horizontal_bar":
        return _svg_bar(spec, horizontal=True)
    # grouped_bar/stacked_bar/scatter/histogram/comparison: se simplifican a la primera serie en
    # barras — cobertura razonable sin un motor de gráficos distinto por tipo (ver progreso del
    # proyecto: limitación conocida y documentada, no oculta).
    return _svg_bar(spec)


def _rows(block: Block) -> tuple[list[str], list[list[Any]]]:
    if block.kind in ("table", "annex"):
        return [str(c) for c in block.data.get("columns", [])], list(block.data.get("rows", []))
    return [], []


def _annex_notice(block: Block) -> str | None:
    if block.kind != "annex" or not block.data.get("truncated"):
        return None
    shown, total = len(block.data.get("rows", [])), block.data.get("total_rows")
    return f"Mostrando {shown} de {total} filas — el resto no se ha omitido en silencio, solo no entra en este documento."


def _render_block(block: Block, *, chart_of: Any) -> str:
    if block.kind == "kpis":
        cards = "".join(
            f'<div class="kpi-card"><div class="kpi-value">{_esc(v)}</div><div class="kpi-label">{_esc(k)}</div></div>'
            for k, v in block.data.items()
        )
        return f'<section class="block"><h2>{_esc(block.title)}</h2><div class="kpi-grid">{cards}</div></section>'

    if block.kind == "section":
        rows = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in block.data.items())
        return f'<section class="block"><h2>{_esc(block.title)}</h2><dl class="section-list">{rows}</dl></section>'

    if block.kind == "chart":
        svg = _chart_svg(block.data)
        return f'<section class="block"><h2>{_esc(block.title)}</h2><div class="chart">{svg}</div></section>'

    if block.kind == "warnings":
        items = "".join(
            f'<li class="warning-item" style="border-left-color:{SEVERITY_COLOR.get(i.get("severity"), MUTED)}">'
            f'<span class="warning-badge" style="color:{SEVERITY_COLOR.get(i.get("severity"), MUTED)}">'
            f'{_esc(SEVERITY_LABEL.get(i.get("severity"), i.get("severity")))} · {_esc(i.get("code"))}</span>'
            f'<p>{_esc(i.get("message"))}</p></li>'
            for i in block.data.get("items", [])
        )
        return f'<section class="block"><h2>{_esc(block.title)}</h2><ul class="warning-list">{items}</ul></section>'

    if block.kind == "narrative":
        items = "".join(
            f'<li class="narrative-item"><span class="narrative-badge">{_esc(NARRATIVE_LABEL.get(s.get("kind"), s.get("kind")))}</span>'
            f'<p>{_esc(s.get("text"))}</p>'
            + (
                f'<p class="evidence">Evidencia: {_esc(", ".join(f"{k}: {v}" for k, v in (s.get("evidence") or {}).items()))}</p>'
                if s.get("evidence")
                else ""
            )
            + "</li>"
            for s in block.data.get("statements", [])
        )
        return f'<section class="block"><h2>{_esc(block.title)}</h2><ul class="narrative-list">{items}</ul></section>'

    if block.kind == "methodology":
        items = "".join(f"<li>{_esc(n)}</li>" for n in block.data.get("notes", []))
        return f'<section class="block"><h2>{_esc(block.title)}</h2><ol class="methodology-list">{items}</ol></section>'

    # table / annex (y cualquier otro: fallback de pares clave/valor)
    columns, rows = _rows(block)
    notice = _annex_notice(block)
    notice_html = f'<p class="annex-notice">{_esc(notice)}</p>' if notice else ""
    if not columns:
        rows_html = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in block.data.items())
        return f'<section class="block"><h2>{_esc(block.title)}</h2><dl class="section-list">{rows_html}</dl></section>'
    chart_html = ""
    spec = chart_of(block)
    if spec:
        chart_html = f'<div class="chart">{_chart_svg(spec)}</div>'
    head = "".join(f"<th scope=\"col\">{_esc(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row) + "</tr>" for row in rows
    )
    return (
        f'<section class="block"><h2>{_esc(block.title)}</h2>{notice_html}{chart_html}'
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></section>'
    )


_STYLE = f"""
:root {{ --navy:{NAVY}; --gold:{GOLD}; --light:{LIGHT}; --line:{LINE}; --muted:{MUTED}; }}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
body {{ margin:0; font-family:'Aptos','Segoe UI',system-ui,-apple-system,sans-serif; color:#283045; background:#f2f4f8; line-height:1.55; }}
.page {{ max-width:1120px; margin:32px auto; background:#fff; padding:42px 44px 52px; box-shadow:0 16px 60px rgba(27,37,89,.09); border:1px solid #e6e8ed; border-radius:22px; }}
.header {{ display:flex; align-items:center; gap:26px; padding:0 0 28px; border-bottom:2px solid var(--gold); margin-bottom:30px; }}
.header img {{ height:84px; width:auto; max-width:180px; object-fit:contain; flex-shrink:0; }}
.header h1 {{ color:var(--navy); letter-spacing:-.03em; font-weight:750; font-size:clamp(1.65rem,3vw,2.25rem); line-height:1.15; margin:0 0 12px; overflow-wrap:anywhere; }}
.header .meta {{ color:var(--muted); font-size:.9rem; }}
.block {{ margin-bottom:34px; break-inside:auto; }}
.block h2 {{ color:var(--navy); font-weight:700; font-size:1.22rem; letter-spacing:-.015em; border-left:5px solid var(--gold); padding-left:14px; margin:0 0 20px; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(205px,1fr)); gap:14px; }}
.kpi-card {{ background:linear-gradient(145deg,#fff 0%,#f7f5f2 100%); border:1px solid var(--line); border-top:3px solid var(--gold); border-radius:14px; padding:22px 21px 19px; min-height:118px; box-shadow:0 5px 14px rgba(27,37,89,.04); text-align:left; overflow-wrap:anywhere; }}
.kpi-value {{ color:var(--navy); font-weight:760; font-size:clamp(1.4rem,2.6vw,2rem); letter-spacing:-.035em; line-height:1.2; font-variant-numeric:tabular-nums; }}
.kpi-label {{ color:var(--muted); font-weight:550; font-size:.82rem; margin-top:13px; }}
.section-list {{ display:grid; grid-template-columns:minmax(150px,30%) minmax(0,1fr); gap:0 22px; border-top:1px solid var(--line); }}
.section-list dt,.section-list dd {{ border-bottom:1px solid var(--line); padding:12px 0; }}
.section-list dt {{ color:var(--muted); font-weight:650; font-size:.88rem; }}
.section-list dd {{ margin:0; overflow-wrap:anywhere; }}
.chart {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:20px 22px; overflow:auto; }}
.chart svg {{ max-width:100%; height:auto; }}
.table-wrap {{ overflow-x:auto; border-radius:12px; border:1px solid var(--line); }}
table {{ width:100%; border-collapse:separate; border-spacing:0; font-size:.9rem; font-variant-numeric:tabular-nums; }}
th {{ background:var(--navy); color:#fff; text-align:left; padding:12px 15px; position:sticky; top:0; z-index:1; white-space:normal; font-weight:650; }}
td {{ padding:12px 15px; border-bottom:1px solid var(--line); overflow-wrap:anywhere; vertical-align:middle; }}
tbody tr:nth-child(even) {{ background:#f8f6f3; }}
tbody tr:hover {{ background:#f3f4fa; }}
tbody tr:last-child td {{ border-bottom:0; }}
td:first-child {{ color:var(--navy); font-weight:640; }}
.warning-list,.narrative-list,.methodology-list {{ list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:13px; }}
.warning-item {{ border-left:4px solid var(--muted); background:var(--light); padding:16px 20px; border-radius:10px; }}
.warning-item p,.narrative-item p {{ margin:8px 0 0; }}
.warning-badge,.narrative-badge {{ font-weight:750; font-size:.72rem; letter-spacing:.055em; }}
.narrative-item {{ border-left:4px solid var(--gold); background:var(--light); padding:17px 21px; border-radius:10px; }}
.narrative-item .evidence {{ color:var(--muted); font-size:.8rem; font-style:italic; margin:8px 0 0; }}
.methodology-list {{ list-style:decimal; padding-left:1.8rem; }}
.annex-notice {{ color:#8b5f26; font-size:.85rem; font-weight:600; }}
.donut-wrap {{ display:flex; align-items:center; gap:28px; flex-wrap:wrap; }}
.legend-dot {{ display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:7px; }}
.legend {{ font-size:.85rem; display:flex; flex-wrap:wrap; column-gap:18px; row-gap:9px; color:var(--muted); }}
footer {{ color:var(--muted); border-top:1px solid var(--line); padding-top:18px; font-size:.78rem; text-align:right; margin-top:34px; }}
@media (max-width:700px) {{ .page{{margin:0;padding:24px 16px;border-radius:0;box-shadow:none;}} .header{{gap:15px;align-items:flex-start;flex-direction:column;}} .header img{{height:60px;}} .kpi-grid{{grid-template-columns:repeat(auto-fit,minmax(145px,1fr));}} .section-list{{grid-template-columns:1fr;}} .section-list dt{{border-bottom:none;padding-bottom:0;}} .section-list dd{{padding-top:2px;}} }}
@media print {{ @page{{margin:16mm;}} body{{background:#fff;}} .page{{max-width:none;margin:0;border:0;padding:0;box-shadow:none;}} .header,.kpi-card,.warning-item,.narrative-item{{break-inside:avoid;}} .block{{break-inside:auto;}} tr{{break-inside:avoid;}} th{{position:static;}} .chart{{break-inside:avoid;}} }}
"""


def to_html(doc: Document, generated: datetime, logo: Path | None = None) -> bytes:
    # Ningun HTML corporativo debe salir sin el logotipo embebido.
    logo_uri = _logo_data_uri(resolve_logo(logo))
    if not logo_uri:
        raise FileNotFoundError("El logotipo de Sunset Beach Club es obligatorio")
    logo_html = f'<img src="{logo_uri}" alt="Logotipo Sunset Beach Club" />' 
    meta = "  ·  ".join(x for x in [doc.subtitle, *doc.badges] if x)
    has_explicit_chart = any(b.kind == "chart" for b in doc.blocks)

    def chart_of(block: Block) -> dict[str, Any] | None:
        if block.kind != "table" or has_explicit_chart:
            return None
        columns, rows = _rows(block)
        return chart_spec(block.title, columns, rows)

    blocks_html = "".join(_render_block(b, chart_of=chart_of) for b in doc.blocks)
    html_doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_esc(doc.title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="page">
  <header class="header">
    {logo_html}
    <div>
      <h1>{_esc(doc.title)}</h1>
      <div class="meta">{_esc(meta)}</div>
    </div>
  </header>
  <main>{blocks_html}</main>
  <footer>Sunset Beach Club · Generado el {_esc(generated.strftime("%d/%m/%Y %H:%M"))}</footer>
</div>
</body>
</html>"""
    return html_doc.encode("utf-8")
