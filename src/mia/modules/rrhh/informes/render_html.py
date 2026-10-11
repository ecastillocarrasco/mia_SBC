"""Renderizador HTML del motor documental universal (Bloque II, Fase E).

Mismo contrato que PDF/XLSX/PPTX (``Document``/``Block`` de ``document.py``): nunca recalcula ninguna
cifra, solo pinta lo que ya decidió el backend. Autocontenido (sin CSS/JS externos, logo incrustado en
base64) para que un informe HTML se pueda abrir o archivar sin depender de ninguna ruta externa —
mismo motivo por el que el logotipo SBC se incrusta y nunca se referencia por URL.

Gráficos: SVG generado en el propio servidor (sin ninguna librería de JavaScript ni CDN) a partir de la
MISMA especificación ``{type, title, labels, series}`` que ya consumen PDF/XLSX/PPTX
(``mia.modules.rrhh.charts``) — ni un motor de gráficos paralelo ni una re-derivación.

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

from mia.modules.rrhh.charts import chart_spec
from mia.modules.rrhh.informes.document import Block, Document

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
    series = spec["series"][:1]
    values = [v or 0.0 for v in series[0]["values"]] if series else []
    width, height = 560, 60 + 32 * len(labels)
    if not values:
        return ""
    vmax = max(values) or 1.0
    bars = []
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        y = 20 + i * 32
        bar_w = max(2.0, (value / vmax) * 380)
        bars.append(
            f'<text x="0" y="{y + 14}" font-size="11" fill="{MUTED}">{_esc(label)[:28]}</text>'
            f'<rect x="150" y="{y}" width="{bar_w:.1f}" height="20" rx="3" fill="{PALETTE[i % len(PALETTE)]}" />'
            f'<text x="{150 + bar_w + 6:.1f}" y="{y + 14}" font-size="11" fill="{NAVY}">{_esc(round(value, 2))}</text>'
        )
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
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(spec.get("title"))}">' + "".join(parts) + "</svg>"


def _chart_svg(spec: dict[str, Any]) -> str:
    kind = spec.get("type")
    if kind == "donut":
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
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: Helvetica, Arial, sans-serif; color:#222; background:#fff; }}
.page {{ max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }}
.header {{ display:flex; align-items:center; gap:16px; border-bottom:3px solid var(--gold); padding-bottom:12px; margin-bottom:24px; }}
.header img {{ height:56px; }}
.header h1 {{ color:var(--navy); font-size:1.6rem; margin:0; }}
.header .meta {{ color:var(--muted); font-size:0.9rem; }}
.block {{ margin-bottom:32px; page-break-inside: avoid; }}
.block h2 {{ color:var(--navy); font-size:1.15rem; border-left:4px solid var(--gold); padding-left:10px; margin-bottom:12px; }}
.kpi-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:12px; }}
.kpi-card {{ background:var(--light); border:1px solid var(--line); border-radius:8px; padding:14px; text-align:center; }}
.kpi-value {{ color:var(--navy); font-weight:bold; font-size:1.3rem; }}
.kpi-label {{ color:var(--muted); font-size:0.78rem; margin-top:4px; }}
.section-list {{ display:grid; grid-template-columns: max-content 1fr; gap:6px 16px; }}
.section-list dt {{ color:var(--muted); font-weight:bold; font-size:0.85rem; }}
.section-list dd {{ margin:0; }}
.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:0.88rem; }}
th {{ background:var(--navy); color:#fff; text-align:left; padding:8px; position:sticky; top:0; }}
td {{ padding:7px 8px; border-bottom:1px solid var(--line); }}
tbody tr:nth-child(even) {{ background:var(--light); }}
.warning-list, .narrative-list, .methodology-list {{ list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:10px; }}
.warning-item {{ border-left:4px solid var(--muted); background:var(--light); padding:8px 12px; border-radius:4px; }}
.warning-badge, .narrative-badge {{ font-weight:bold; font-size:0.78rem; }}
.narrative-item {{ border-left:4px solid var(--gold); background:var(--light); padding:8px 12px; border-radius:4px; }}
.narrative-item .evidence {{ color:var(--muted); font-size:0.78rem; font-style:italic; margin:4px 0 0; }}
.methodology-list {{ list-style:decimal; padding-left:1.2rem; }}
.annex-notice {{ color:var(--gold); font-style:italic; font-size:0.85rem; }}
.donut-wrap {{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; }}
.legend-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }}
.legend {{ font-size:0.85rem; }}
footer {{ color:var(--muted); font-size:0.78rem; text-align:right; margin-top:32px; }}
@media (max-width: 600px) {{
  .header {{ flex-direction:column; align-items:flex-start; }}
  .kpi-grid {{ grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }}
}}
@media print {{
  .block {{ page-break-inside: avoid; }}
  body {{ background:#fff; }}
}}
"""


def to_html(doc: Document, generated: datetime, logo: Path | None = None) -> bytes:
    logo_uri = _logo_data_uri(logo)
    logo_html = f'<img src="{logo_uri}" alt="Logotipo Sunset Beach Club" />' if logo_uri else ""
    meta = "  ·  ".join(x for x in [doc.subtitle, *doc.badges] if x)

    def chart_of(block: Block) -> dict[str, Any] | None:
        if block.kind != "table":
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
