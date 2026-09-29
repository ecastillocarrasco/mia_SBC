"""Traducción de las presentaciones de mIA al formato que pinta el universo 2D anterior.

El 2D (idéntico al del sistema anterior) espera sus propias estructuras:
  * ``data.table``      → {title, subtitle, columns: [{key, label}], rows: [{key: valor}], total, searchable}
  * ``data.cards``      → [{label, value, unit}]
  * ``data.presentation`` con schema ``mia.employee360.presentation`` para la ficha 360
  * ``actions``         → [{type: download|open_document, url, label}]
Se evita a propósito ``visualizations`` y los dominios vacaciones/ausencias/nóminas/turnos: en el 2D
activan vistas que recortan columnas o esperan campos del sistema anterior.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from mia.domains.charts import chart_spec
from mia.text import humanize_label

MAX_CARDS = 8


def _flat(value: Any) -> Any:
    """Valor pintable en una celda o tarjeta: los objetos anidados se convierten en texto legible."""
    if isinstance(value, dict):
        return " · ".join(f"{_label(k)}: {_flat(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, list):
        return ", ".join(str(_flat(v)) for v in value if v not in (None, ""))
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return value


def _label(key: str) -> str:
    return humanize_label(key)


def table_view(p: dict[str, Any], subtitle: str = "Información estructurada") -> dict[str, Any]:
    columns = [str(c) for c in p.get("columns") or []]
    rows = [
        {col: _flat(row[i]) if i < len(row) else None for i, col in enumerate(columns)} for row in p.get("rows") or []
    ]
    return {
        "title": p.get("title") or "Detalle",
        "subtitle": subtitle,
        "columns": [{"key": c, "label": c} for c in columns],
        "rows": rows,
        "total": len(rows),
        "searchable": True,
    }


def _list_table(title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    columns = list(dict.fromkeys(k for item in items for k in item))
    return table_view(
        {
            "title": title,
            "columns": [_label(c) for c in columns],
            "rows": [[item.get(c) for c in columns] for item in items],
        }
    )


def cards_from(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": _label(k), "value": _flat(v)}
        for k, v in values.items()
        if v not in (None, "", [], {}) and not isinstance(v, list) and not k.startswith("_")
    ][:MAX_CARDS]


SECTION_ORDER: dict[str, tuple[str, ...]] = {
    "hoy": ("turno", "ausencia_en_curso"),
    "employment": ("Situacion", "Departamento", "Puesto", "Edad"),
    "datos_de_contacto": ("email", "telefono", "codigo_empleado", "nacionalidad", "cuenta"),
    "vacaciones": ("saldo_actual", "saldo_total", "pendientes", "proximas", "consumido"),
    "bajas": ("periodos", "dias"),
    "documentacion": ("nominas_este_anio", "nominas_no_leidas", "documentos_firmados", "documentos_por_tipo"),
}
KPI_ORDER = ("saldo_vacaciones", "dias_de_baja_este_anio", "nominas_no_leidas", "documentos_firmados")
_WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _ordered(data: dict[str, Any], order: tuple[str, ...]) -> dict[str, Any]:
    rank = {k: i for i, k in enumerate(order)}
    return dict(sorted(data.items(), key=lambda kv: (rank.get(kv[0], len(rank)), 0)))


def _pretty_date(value: Any) -> Any:
    """«2026-10-03» → «sáb 03/10/2026»; cualquier otro valor se deja tal cual."""
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return value
    return f"{_WEEKDAYS[day.weekday()]} {day:%d/%m/%Y}"


def employee360_view(card: dict[str, Any]) -> dict[str, Any]:
    labor = card.get("ficha_laboral") or {}
    org = card.get("organizacion") or {}
    vac = card.get("vacaciones") or {}
    today = card.get("hoy") or {}
    kpis = card.get("indicadores") or {}
    name = str(card.get("nombre") or "Empleado")
    week = [
        {
            "Fecha": d.get("fecha"),
            "FechaISO": d.get("fecha"),
            "Turno": d.get("horario") or d.get("tipo"),
            "Tipo": d.get("tipo"),
        }
        for d in card.get("semana_actual") or []
    ]
    timeline = [
        {
            "date": h.get("fecha"),
            "display_date": _pretty_date(h.get("fecha")),
            "title": str(h.get("hito", "Hito")).capitalize(),
            "subtitle": " · ".join(f"{_label(k)}: {v}" for k, v in h.items() if k not in {"hito", "fecha"} and v),
            "state": "info",
        }
        for h in card.get("proximos_hitos") or []
    ]
    shift_today = today.get("turno")
    shift_label = (
        shift_today.get("horario") or shift_today.get("tipo") if isinstance(shift_today, dict) else shift_today
    )
    sections: list[dict[str, Any]] = [
        {
            "id": "hoy",
            "title": "Hoy",
            "layout": "metric_detail",
            "data": {"turno": shift_label, "ausencia_en_curso": _flat(today.get("ausencia_en_curso")) or "No consta"},
        },
        {"id": "week", "title": "Semana actual", "layout": "week_strip", "items": week},
        {"id": "next", "title": "Próximos hitos", "layout": "timeline", "items": timeline},
        {
            "id": "employment",
            "title": "Ficha laboral",
            "layout": "definition_grid",
            "data": {
                "Situacion": "Activo" if card.get("activo", True) else "Inactivo",
                "Departamento": labor.get("departamento"),
                "Puesto": labor.get("puesto"),
                "Edad": labor.get("edad"),
            },
        },
        {
            "id": "datos_de_contacto",
            "title": "Datos de contacto",
            "layout": "metric_detail",
            "data": {k: labor.get(k) for k in ("email", "telefono", "cuenta", "codigo_empleado", "nacionalidad")},
        },
        {
            "id": "organization",
            "title": "Organización",
            "layout": "people_chips",
            "data": {
                "ResponsableDirecto": org.get("responsable_directo"),
                "Responsables": org.get("responsables_del_departamento") or [],
                "Departamento": labor.get("departamento"),
            },
        },
        {
            "id": "vacaciones",
            "title": "Vacaciones",
            "layout": "metric_detail",
            "data": {k: _flat(v) for k, v in vac.items()},
        },
        {
            "id": "bajas",
            "title": "Bajas este año",
            "layout": "metric_detail",
            "data": {k: _flat(v) for k, v in (card.get("bajas_este_anio") or {}).items()},
        },
        {
            "id": "documentacion",
            "title": "Documentación y nóminas",
            "layout": "metric_detail",
            "data": {k: _flat(v) for k, v in (card.get("documentacion") or {}).items()},
        },
    ]
    if card.get("alertas_calidad"):
        sections.append(
            {
                "id": "calidad",
                "title": "Calidad de los datos",
                "layout": "metric_detail",
                "data": {a.get("componente", "aviso"): a.get("motivo") for a in card["alertas_calidad"]},
            }
        )
    if card.get("historico"):
        sections.append(
            {
                "id": "historico",
                "title": "Histórico",
                "layout": "metric_detail",
                "data": {k: f"{len(v)} registros" for k, v in card["historico"].items()},
            }
        )
    for section in sections:
        if section.get("id") in SECTION_ORDER and isinstance(section.get("data"), dict):
            section["data"] = _ordered(section["data"], SECTION_ORDER[section["id"]])
    kpis = _ordered(kpis, KPI_ORDER)
    return {
        "schema": "mia.employee360.presentation",
        "version": "mia-1",
        "layout": "employee_360_premium",
        "hero": {
            "title": name,
            "subtitle": " · ".join(filter(None, [labor.get("puesto"), labor.get("departamento")])),
            "initials": "".join(w[0] for w in name.split()[:2]).upper(),
            "status": "active" if card.get("activo", True) else "inactive",
            "badges": [b for b in (labor.get("puesto"), labor.get("departamento")) if b],
        },
        "kpis": [{"id": k, "label": _label(k), "value": _flat(v), "variant": "info"} for k, v in kpis.items()],
        "sections": sections,
        "quick_actions": [
            {"id": f"qa{i}", "label": a, "prompt": a} for i, a in enumerate(card.get("acciones_rapidas") or [])
        ],
    }


# Claves del resumen de las herramientas que no aportan a la pantalla (van en la tabla o son internas).
SKIP_SUMMARY = {"al_dia", "regla", "desde", "hasta", "empleado_id", "candidato_id", "estado", "anio", "fecha"}
NOTE_KEYS = {"nota", "criterio", "mensaje", "nota_bajas", "persona_destacada"}


def _is_scalar(v: Any) -> bool:
    return v is not None and v != "" and not isinstance(v, dict | list)


def summary_view(summaries: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Del resumen de cada herramienta: tarjetas (cifras), comparativa (desgloses por tipo o por
    departamento), lectura contextual (desgloses simples y notas) y observaciones (avisos)."""
    cards: list[dict[str, Any]] = []
    comparison: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    insights: list[str] = []
    quality: list[str] = []
    for item in summaries:
        for key, value in (item.get("summary") or {}).items():
            if key in SKIP_SUMMARY or key.startswith("_"):
                continue
            if key == "aviso" and isinstance(value, str):
                quality.append(value)
            elif key in NOTE_KEYS:
                insights.append(f"{_label(key)}: {_flat(value)}" if not isinstance(value, str) else value)
            elif key == "alertas_calidad" and isinstance(value, list):
                quality += [str(_flat(a)) for a in value]
            elif _is_scalar(value) and isinstance(value, int | float) and not isinstance(value, bool):
                cards.append({"label": _label(key), "value": value})
            elif isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
                # {tipo: {personas, periodos, dias}} → comparativa: una fila por métrica, una columna por tipo.
                metrics = list(dict.fromkeys(m for v in value.values() for m in v))
                comparison += [
                    {"metrica": f"{_label(key)} · {_label(m)}", **{str(col): v.get(m) for col, v in value.items()}}
                    for m in metrics
                    if all(_is_scalar(v.get(m)) or v.get(m) is None for v in value.values())
                ]
            elif isinstance(value, dict) and value and all(_is_scalar(v) for v in value.values()):
                if key.startswith(("por_", "grupos")) and (
                    spec := chart_spec(_label(key), [_label(key), "Personas"], [[k, v] for k, v in value.items()])
                ):
                    charts.append(spec)
                shown = list(value.items())[:12]
                rest = "" if len(value) <= 12 else f" … y {len(value) - 12} más"
                insights.append(f"{_label(key)}: " + " · ".join(f"{k} {_flat(v)}" for k, v in shown) + rest)
    return {
        "charts": charts,
        "cards": cards,
        "comparacion": comparison,
        "insights": list(dict.fromkeys(insights)),
        "alertas_calidad": list(dict.fromkeys(quality)),
    }


# ---------------------------------------------------------------------------------------- correo
_SENDER = re.compile(r"^\s*(?P<name>.*?)\s*<(?P<address>[^>]+)>\s*$")


def _sender_parts(value: Any) -> tuple[str, str]:
    match = _SENDER.match(str(value or ""))
    return (match["name"] or match["address"], match["address"]) if match else (str(value or ""), "")


def mail_rows_view(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Formato del panel de correo del 2D (mail_rows / mail_summary), con la referencia de cada correo."""
    view = []
    for r in rows:
        name, address = _sender_parts(r.get("from"))
        view.append(
            {
                "ref": r.get("ref"),
                "sender_name": name,
                "sender_address": address,
                "subject": r.get("subject"),
                "received_at": r.get("received_at"),
                "has_attachments": bool(r.get("has_attachments")),
                "preview": r.get("preview"),
            }
        )
    return {
        "mail_rows": view,
        "mail_summary": {"mailbox": "Buzón de RRHH", "total_unread": None, "total_conversations": len(view)},
    }


def _mail_message_view(p: dict[str, Any]) -> dict[str, Any]:
    name, address = _sender_parts(p.get("de"))
    return {
        "ref": p.get("ref"),
        "from_name": name,
        "from_address": address,
        "to": p.get("para") or [],
        "subject": p.get("asunto"),
        "received_at": p.get("recibido"),
        "text": p.get("texto"),
        "attachments": p.get("adjuntos") or [],
    }


# ---------------------------------------------------------------------------------------- gráficos
def chart_from_table(view: dict[str, Any]) -> dict[str, Any] | None:
    """Gráfico de un recuento por categorías (tabla de dos columnas: categoría y cantidad)."""
    columns = [c["label"] for c in view.get("columns") or []]
    keys = [c["key"] for c in view.get("columns") or []]
    rows = [[r.get(k) for k in keys] for r in view.get("rows") or []]
    return chart_spec(view.get("title"), columns, rows)


def _absorb(
    p: dict[str, Any],
    data: dict[str, Any],
    actions: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> None:
    """Traduce una presentación de mIA a lo que pinta el 2D (tablas, tarjetas, acciones, correo…)."""
    kind = p.get("type")
    if kind == "employee_360":
        data["presentation"] = employee360_view(p)
    elif kind == "table" and p.get("mail_rows") is not None:
        data.update(mail_rows_view(p["mail_rows"]))
    elif kind == "mail":
        data["mail_message"] = _mail_message_view(p)
    elif kind == "mail_draft":
        data["mail_draft"] = {k: p.get(k) for k in ("borrador", "texto", "responde_a", "envio_habilitado")}
    elif kind == "table":
        tables.append(table_view(p))
    elif kind == "dashboard":
        cards.extend(cards_from(p.get("kpis") or {}))
        tables.extend([table_view(t, "Panel") for t in p.get("tables") or [] if t.get("rows")])
    elif kind == "download" and p.get("url"):
        actions.append({"type": "download", "url": p["url"], "label": f"Descargar {p.get('format', 'informe')}"})
    else:
        body = {k: v for k, v in p.items() if k not in {"type", "title"}}
        cards.extend(cards_from(body))
        tables.extend(
            [
                _list_table(_label(k), v)
                for k, v in body.items()
                if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)
            ]
        )
        for key in ("documento", "enlace", "url"):
            if isinstance(body.get(key), str) and body[key].startswith("/api/"):
                actions.append({"type": "open_document", "url": body[key], "label": "Abrir documento"})


def legacy_view(
    presentations: list[dict[str, Any]], summaries: list[dict[str, Any]] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(data, actions) en el formato del 2D a partir de TODAS las presentaciones y resúmenes del turno."""
    data: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    extra = summary_view(summaries or [])
    for p in presentations:
        _absorb(p, data, actions, cards, tables)
    every_table = list(tables)
    if tables:
        # El 2D pinta una tabla por respuesta: la más completa; el resto se ofrece como tarjeta de contexto.
        tables.sort(key=lambda t: (t["total"], len(t["columns"])), reverse=True)
        data["table"] = tables[0]
        cards += [{"label": t["title"], "value": t["total"], "unit": "registros"} for t in tables[1:]]
    _merge_extra(data, cards, extra)
    charts = [c for t in every_table if (c := chart_from_table(t))][:2] or extra["charts"][:1]
    if charts:
        data["charts"] = charts
    return data, actions


def _merge_extra(data: dict[str, Any], cards: list[dict[str, Any]], extra: dict[str, list[Any]]) -> None:
    if "presentation" not in data:  # la ficha 360 ya lleva sus propios indicadores
        cards = cards + extra["cards"]
        for key in ("comparacion", "insights"):
            if extra[key]:
                data[key] = extra[key]
    if extra["alertas_calidad"]:
        data["alertas_calidad"] = extra["alertas_calidad"]
    unique = list({c["label"]: c for c in reversed(cards)}.values())[::-1]
    if unique:
        data["cards"] = unique[: MAX_CARDS * 2]
