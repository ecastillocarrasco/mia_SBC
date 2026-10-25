"""Modelo común de documento: resultados de cualquier dominio se normalizan a bloques y se
renderizan como PDF, Excel, PowerPoint, HTML o Word."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from mia.text import format_number, humanize_label

NarrativeKind = Literal["fact", "interpretation", "hypothesis", "recommendation"]
"""Bloque II, sección 9 (ajuste de Fase D, condición 4 de la aprobación): toda afirmación narrativa
debe declarar explícitamente de qué tipo es — nunca mezclar un hecho verificado con una hipótesis sin
que quien lo lea pueda distinguirlos."""

_NARRATIVE_LABELS: dict[NarrativeKind, str] = {
    "fact": "Hecho verificado",
    "interpretation": "Interpretación",
    "hypothesis": "Hipótesis",
    "recommendation": "Recomendación",
}

_SEVERITY_LABELS: dict[str, str] = {
    "blocker": "Bloqueante",
    "data_quality": "Calidad de datos",
    "info": "Información",
}

# Claves de distribución en el resumen (orden de preferencia para el gráfico)
_DIST_KEYS = (
    "seleccion_por_departamento",
    "grupos",
    "por_departamento",
    "por_tipo",
    "por_franja",
    "distribucion",
)

# Claves escalares del resumen que NO son interesantes como KPIs de presentación
_SKIP_KPI_KEYS = frozenset({
    "fecha", "desde", "hasta", "periodo", "criterio", "nota", "departamento",
    "poblacion", "mensaje", "ultima_sincronizacion", "actualizacion",
    "personas",  # lista de objetos, no escalar
})

LABELS = {
    "hoy": "Hoy",
    "semana_actual": "Semana actual",
    "proximos_hitos": "Próximos hitos",
    "ficha_laboral": "Ficha laboral",
    "organizacion": "Organización",
    "vacaciones": "Vacaciones",
    "bajas_este_anio": "Bajas este año",
    "documentacion": "Documentación",
    "indicadores": "Indicadores",
}
SKIP = {"type", "title", "acciones_rapidas", "al_dia", "aviso", "regla", "nota"}


@dataclass
class Block:
    kind: str  # kpis · section · table · chart · warnings · narrative · methodology · annex
    title: str
    data: Any
    """Para ``kind="chart"``: el dict con forma ``{type, title, labels, series:[{name, values}]}`` que ya
    producen ``mia.reporting.charts.chart_spec()`` y sus constructores (``bar_chart()``,
    ``donut_chart()``, ``time_series_chart()``...). Bloque de PRIMERA CLASE (Bloque II, sección 10): el
    backend decide el tipo de gráfico y calcula los datos UNA sola vez; los renderizadores (PDF,
    XLSX, PPTX, HTML y DOCX) lo consumen sin volver a derivarlo. Para tablas normales (sin
    este bloque explícito), los renderizadores siguen derivando un gráfico heurísticamente a partir de
    un bloque ``table`` 2-columnas, como ya hacían (compatibilidad hacia atrás, ver ``render.py``).

    Para ``kind="table"`` o ``"annex"``: admite opcionalmente la clave ``data["kpis"]``, un dict
    etiqueta→valor igual que el ``data`` de un bloque ``kind="kpis"`` independiente. Cuando está
    presente, todos los renderizadores (PDF/XLSX/PPTX/DOCX/HTML) dibujan esas tarjetas KPI justo antes
    de la tabla de ESTE MISMO bloque, bajo el mismo título — nunca como un bloque ``kpis`` aparte.
    Pensado para informes con una entidad por bloque (una persona, un proyecto…) que necesitan
    "resumen + detalle" juntos en la misma página/pestaña/diapositiva: un bloque ``kpis`` + un bloque
    ``table`` consecutivos con el mismo título producirían dos pestañas/diapositivas distintas en
    Excel/PowerPoint para la misma entidad, que es justo lo que este sidecar evita (ver
    ``mia.modules.rrhh.fichajes.informe._build_document`` para un ejemplo real)."""


@dataclass
class Document:
    title: str
    blocks: list[Block] = field(default_factory=list)
    subtitle: str | None = None
    badges: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ bloques de Fase D (sección 9)
def warnings_block(title: str, issues: list[dict[str, Any]]) -> Block:
    """``issues``: lista de dicts con la forma de ``HomogeneityIssue.to_dict()``
    (``mia.analytics.homogeneity``) — severidad, código, mensaje, fuente y contexto. Este módulo no
    importa ``mia.analytics`` a propósito (``mia/query``/``mia/modules/rrhh/informes`` son capas más
    genéricas que no deben depender de un dominio analítico concreto): el llamador convierte con
    ``.to_dict()`` antes de pasarlas aquí."""
    for issue in issues:
        if issue.get("severity") not in _SEVERITY_LABELS:
            raise ValueError(f"Severidad de advertencia desconocida: {issue.get('severity')!r}")
        if not issue.get("code") or not issue.get("message"):
            raise ValueError("Toda advertencia necesita código y mensaje: no se admite una advertencia muda.")
    return Block("warnings", title, {"items": issues})


def narrative_statement(
    kind: NarrativeKind, text: str, *, evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Una afirmación narrativa individual. Un ``fact`` EXIGE evidencia verificable (fuente/métrica/
    periodo/valor, sección 16) — nunca una cifra sin respaldo del backend; se rechaza en el momento de
    construirla, no en el de mostrarla."""
    if kind == "fact" and not evidence:
        raise ValueError(
            "Una afirmación de tipo 'fact' exige evidencia verificable (source/metric/period/value): "
            "no se permiten conclusiones cuantitativas sin respaldo del backend."
        )
    return {"kind": kind, "text": text, "evidence": dict(evidence or {})}


def narrative_block(title: str, statements: list[dict[str, Any]]) -> Block:
    return Block("narrative", title, {"statements": statements})


def methodology_block(title: str, notes: list[str]) -> Block:
    return Block("methodology", title, {"notes": list(notes)})


def annex_block(
    title: str, columns: list[str], rows: list[list[Any]], *, max_rows: int = 5000
) -> Block:
    """Tabla extensa de detalle. Nunca trunca en silencio (sección 19): si ``rows`` supera
    ``max_rows``, se recortan las filas mostradas pero ``total_rows``/``truncated`` quedan explícitos
    en el propio bloque para que el renderizador SIEMPRE pueda avisarlo."""
    total = len(rows)
    truncated = total > max_rows
    return Block(
        "annex",
        title,
        {
            "columns": columns,
            "rows": rows[:max_rows] if truncated else rows,
            "total_rows": total,
            "truncated": truncated,
        },
    )


def _label(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def _flat(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, int | float):
        return format_number(value)
    if isinstance(value, dict):
        return ", ".join(f"{_label(k)}: {_flat(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, list):
        return ", ".join(_flat(v) for v in value) or "—"
    return str(value)


def _list_table(title: str, items: list[dict[str, Any]]) -> Block:
    columns = list(dict.fromkeys(k for item in items for k in item))
    return Block(
        "table",
        title,
        {
            "columns": [_label(c) for c in columns],
            "rows": [[_flat(i.get(c)) for c in columns] for i in items],
        },
    )


def _humanize(key: str) -> str:
    return humanize_label(key)


def _pairs(data: dict[str, Any]) -> dict[str, str]:
    """Pares etiqueta → valor legibles, sin los vacíos ni los técnicos."""
    out = {}
    for key, value in data.items():
        if value in (None, "", [], {}) or key in {"cuenta"}:
            continue
        out[_humanize(key)] = ", ".join(map(str, value)) if isinstance(value, list) else _flat(value)
    return out


_WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _day_label(value: Any) -> str:
    """«2026-09-28» → «lun 28/09/2026»."""
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value or "")
    return f"{_WEEKDAYS[day.weekday()]} {day:%d/%m/%Y}"


def _employee_document(card: dict[str, Any]) -> Document:
    """Ficha 360 → secciones legibles (misma estructura que ve el usuario en pantalla)."""
    from mia.api.legacy_view import employee360_view  # noqa: PLC0415

    view = employee360_view(card)
    hero = view["hero"]
    doc = Document(
        str(card.get("title") or f"Ficha 360 · {hero['title']}"),
        subtitle=hero.get("subtitle") or None,
        badges=["Activo" if hero.get("status") == "active" else "Inactivo"],
    )
    if view["kpis"]:
        doc.blocks.append(Block("kpis", "Indicadores", {k["label"]: _flat(k["value"]) for k in view["kpis"]}))
    for section in view["sections"]:
        layout, title = section["layout"], section["title"]
        if layout == "week_strip" and section.get("items"):
            rows = [
                [_day_label(i.get("FechaISO") or i.get("Fecha")), i.get("Turno") or i.get("Tipo")]
                for i in section["items"]
            ]
            doc.blocks.append(Block("table", title, {"columns": ["Día", "Turno"], "rows": rows}))
        elif layout == "timeline" and section.get("items"):
            rows = [
                [i.get("display_date") or i.get("date"), i.get("title"), i.get("subtitle")] for i in section["items"]
            ]
            columns = ["Fecha", "Hito", "Detalle"]
            keep = [n for n in range(3) if any(r[n] for r in rows)]  # sin columnas vacías
            block = {"columns": [columns[n] for n in keep], "rows": [[r[n] for n in keep] for r in rows]}
            doc.blocks.append(Block("table", title, block))
        elif layout in {"metric_detail", "definition_grid", "people_chips"}:
            pairs = _pairs(section.get("data") or {})
            if pairs:
                doc.blocks.append(Block("section", title, pairs))
    return doc


def to_document(
    presentation: dict[str, Any],
    *,
    include_detail: bool = True,
    include_chart: bool = True,
) -> Document:
    kind = presentation.get("type")
    if kind == "employee_360":
        return _employee_document(presentation)
    doc = Document(str(presentation.get("title") or "Informe de mIA"))
    if kind == "table":
        summary = presentation.get("__summary__") or {}

        # KPIs explícitos (p. ej. analisis_economico_nominas, vía table(..., kpis=[...])): tienen
        # prioridad sobre los escalares derivados de __summary__ — son los que la propia herramienta ya
        # decidió destacar, no una heurística genérica sobre lo que sobra.
        explicit_kpis = presentation.get("kpis")
        if isinstance(explicit_kpis, list) and explicit_kpis:
            doc.blocks.append(
                Block(
                    "kpis", "Indicadores",
                    {str(k.get("label")): _flat(k.get("value")) for k in explicit_kpis if isinstance(k, dict)},
                )
            )
        elif not include_detail and summary:
            # KPI scalars from summary when not showing detail table (comportamiento existente, sin tocar)
            kpis = {
                _label(k): _flat(v)
                for k, v in summary.items()
                if not k.startswith("_")
                and k not in _SKIP_KPI_KEYS
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
            }
            if kpis:
                doc.blocks.append(Block("kpis", "Indicadores", kpis))

        # Advertencias del análisis (p. ej. meses sin datos, periodo incompleto, grupos ocultos por
        # k-anonimato): vivían solo en ToolResult.summary y nunca llegaban a ningún informe. Cualquier
        # herramienta que ponga `summary["advertencias"]` (lista de str o de dicts ya estructurados) se
        # beneficia de esto, no solo nóminas.
        advertencias = summary.get("advertencias")
        if advertencias:
            items = [
                {
                    "severity": a.get("severity", "info"),
                    "code": a.get("code", "ANALYSIS_NOTE"),
                    "message": str(a.get("message", "")),
                    "source": a.get("source", "analysis"),
                    "context": dict(a.get("context") or {}),
                }
                if isinstance(a, dict)
                else {"severity": "info", "code": "ANALYSIS_NOTE", "message": str(a), "source": "analysis", "context": {}}
                for a in advertencias
            ]
            doc.blocks.append(warnings_block("Advertencias del análisis", items))

        # Gráficos explícitos (p. ej. analisis_economico_nominas, vía table(..., charts=[...])): de
        # primera clase (Block(kind="chart"), Fase D) — ya calculados por el backend, nunca re-derivados.
        explicit_charts = presentation.get("charts")
        if include_chart and isinstance(explicit_charts, list) and explicit_charts:
            seen_chart_values: set[str] = set()
            for spec in explicit_charts:
                if isinstance(spec, dict) and spec.get("labels") and spec.get("series"):
                    # Ranking y donut de la misma distribución no aportan dos lecturas
                    # distintas al informe y ocupaban páginas completas duplicadas.
                    import json
                    signature = json.dumps(
                        [spec["labels"], [s.get("values") for s in spec["series"]]],
                        ensure_ascii=False, sort_keys=True, default=str,
                    )
                    if signature in seen_chart_values:
                        continue
                    seen_chart_values.add(signature)
                    doc.blocks.append(Block("chart", str(spec.get("title") or doc.title), spec))
        elif include_chart:
            # Chart block from summary distribution data (comportamiento existente, sin tocar)
            for dist_key in _DIST_KEYS:
                dist = summary.get(dist_key)
                if (
                    isinstance(dist, dict)
                    and len(dist) >= 2
                    and all(isinstance(v, (int, float)) for v in dist.values())
                ):
                    dist_block = Block(
                        "table",
                        _label(dist_key),
                        {"columns": ["Categoría", "Personas"], "rows": [[k, v] for k, v in dist.items()]},
                    )
                    doc.blocks.append(dist_block)
                    break

        if include_detail:
            doc.blocks.append(Block("table", doc.title, presentation))

        # Estadísticas adjuntas (p. ej. percentiles salariales): tabla adicional, no se pierden.
        stats = presentation.get("stats")
        if include_detail and isinstance(stats, dict) and stats.get("rows"):
            doc.blocks.append(Block("table", str(stats.get("title") or "Estadísticas"), stats))

        return doc
    if kind == "dashboard":
        doc.blocks.append(Block("kpis", "Indicadores", {_label(k): _flat(v) for k, v in presentation["kpis"].items()}))
        doc.blocks += [Block("table", t["title"], t) for t in presentation.get("tables", []) if t.get("rows")]
        return doc
    if presentation.get("indicadores"):
        doc.blocks.append(
            Block("kpis", "Indicadores", {_label(k): _flat(v) for k, v in presentation["indicadores"].items()})
        )
    for key, value in presentation.items():
        if key in SKIP or key == "indicadores":
            continue
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            doc.blocks.append(_list_table(_label(key), value))
        elif isinstance(value, dict):
            doc.blocks.append(Block("section", _label(key), {_label(k): _flat(v) for k, v in value.items()}))
    simple = {_label(k): _flat(v) for k, v in presentation.items() if k not in SKIP and not isinstance(v, dict | list)}
    if simple:
        doc.blocks.insert(0, Block("section", "Datos", simple))
    return doc
