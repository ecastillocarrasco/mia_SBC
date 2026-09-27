"""Modelo de documento común: cualquier resultado de mIA (tabla, panel, ficha 360, nóminas…)
se normaliza a bloques que después se pintan en PDF, Excel o PowerPoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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


def _label(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def _flat(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sí" if value else "No"
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


def to_document(presentation: dict[str, Any]) -> Document:
    kind = presentation.get("type")
    doc = Document(str(presentation.get("title") or "Informe de mIA"))
    if kind == "table":
        doc.blocks.append(Block("table", doc.title, presentation))
        return doc
    if kind == "dashboard":
        doc.blocks.append(
            Block("kpis", "Indicadores", {_label(k): _flat(v) for k, v in presentation["kpis"].items()})
        )
        doc.blocks += [Block("table", t["title"], t) for t in presentation.get("tables", []) if t.get("rows")]
        return doc
    if presentation.get("indicadores"):
        doc.blocks.append(
            Block(
                "kpis", "Indicadores", {_label(k): _flat(v) for k, v in presentation["indicadores"].items()}
            )
        )
    for key, value in presentation.items():
        if key in SKIP or key == "indicadores":
            continue
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            doc.blocks.append(_list_table(_label(key), value))
        elif isinstance(value, dict):
            doc.blocks.append(Block("section", _label(key), {_label(k): _flat(v) for k, v in value.items()}))
    simple = {
        _label(k): _flat(v)
        for k, v in presentation.items()
        if k not in SKIP and not isinstance(v, dict | list)
    }
    if simple:
        doc.blocks.insert(0, Block("section", "Datos", simple))
    return doc
