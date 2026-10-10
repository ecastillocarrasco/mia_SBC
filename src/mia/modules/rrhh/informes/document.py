"""Modelo de documento común: cualquier resultado de mIA (tabla, panel, ficha 360, nóminas…)
se normaliza a bloques que después se pintan en PDF, Excel o PowerPoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from mia.text import format_number, humanize_label

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
    kind: str  # kpis · section · table
    title: str
    data: Any


@dataclass
class Document:
    title: str
    blocks: list[Block] = field(default_factory=list)
    subtitle: str | None = None
    badges: list[str] = field(default_factory=list)


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
        # Chart block from summary distribution data (e.g. seleccion_por_departamento)
        if include_chart:
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
        # KPI scalars from summary when not showing detail table
        if not include_detail and summary:
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
        if include_detail:
            doc.blocks.append(Block("table", doc.title, presentation))
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
