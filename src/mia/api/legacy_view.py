"""Traducción de las presentaciones de mIA al formato que pinta el universo 2D anterior.

El 2D (idéntico al del sistema anterior) espera sus propias estructuras:
  * ``data.table``      → {title, subtitle, columns: [{key, label}], rows: [{key: valor}], total, searchable}
  * ``data.cards``      → [{label, value, unit}]  (incluye KPIs de primera clase, Fase H)
  * ``data.charts``     → [{type, title, labels, series}] (de primera clase si la herramienta ya los
    calculó; derivados de la tabla/resumen solo si no — nunca ambos, nunca ninguno en silencio)
  * ``data.stats``      → misma forma que ``data.table``, para estadísticas de primera clase (Fase H)
  * ``data.alertas_calidad`` → avisos de privacidad/cobertura/homogeneidad (claves ``advertencias`` o
    ``alertas_calidad`` del resumen de la herramienta — Fase H añadió el reconocimiento de la primera)
  * ``data.comparacion`` → comparativas homogéneas (de un resumen con forma {tipo: {métrica: valor}})
  * ``data.job``         → trabajo en segundo plano del Job Manager (Fase H): {job_id, kind, status,
    periodo, formato} — el mundo 2D sondea su estado real con esto, nunca simula el progreso aquí
  * ``data.presentation`` con schema ``mia.employee360.presentation`` para la ficha 360
  * ``actions``         → [{type: download|open_document, url, label}]
Se evita a propósito ``visualizations`` y los dominios vacaciones/ausencias/nóminas/turnos: en el 2D
activan vistas que recortan columnas o esperan campos del sistema anterior.

Narrativa/metodología/anexo (los otros tipos de bloque del modelo documental, ``mia.modules.rrhh.
informes.document``) NO tienen equivalente aquí porque NUNCA existen a este nivel: solo se generan
dentro de ``to_document()`` al construir un FICHERO (PDF/XLSX/...), nunca en la presentación que una
herramienta devuelve al chat — no hay nada que este módulo pueda perder aquí, porque nunca llega.
Cualquier tipo de presentación que NO sea uno de los reconocidos arriba cae en la rama ``else`` de
``_absorb()``: se extraen tarjetas y sub-tablas genéricas de sus campos (comportamiento explícito,
nunca una pérdida silenciosa), aunque sin el formato específico de su tipo.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mia.modules.correo.presentation import mail_message_view, sender_parts
from mia.reporting.charts import chart_spec
from mia.text import format_number, humanize_label

MAX_CARDS = 8


def _flat(value: Any) -> Any:
    """Valor pintable en una celda o tarjeta: los objetos anidados se convierten en texto legible."""
    if isinstance(value, dict):
        return " · ".join(f"{_label(k)}: {_flat(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, list):
        return ", ".join(str(_flat(v)) for v in value if v not in (None, ""))
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, float):
        return format_number(value)
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


def kpis_to_cards(kpis: Any) -> list[dict[str, Any]]:
    """Los KPI de primera clase de un bloque de tabla (Fase H: ``mia.modules.rrhh.common.table(...,
    kpis=[...])``, lista de ``{label, value, unit?, highlight?}``) al mismo formato que ya pinta el 2D
    (``data.cards``: ``[{label, value, unit}]``) — antes se perdían por completo: ``table_view()`` solo
    traduce columnas/filas, nunca los KPI ya calculados por la herramienta."""
    out: list[dict[str, Any]] = []
    for item in kpis if isinstance(kpis, list) else []:
        if not isinstance(item, dict):
            continue
        label, value = item.get("label"), item.get("value")
        if not label or value in (None, ""):
            continue
        card = {"label": str(label), "value": _flat(value)}
        if item.get("unit"):
            card["unit"] = str(item["unit"])
        out.append(card)
    return out[:MAX_CARDS]


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
GENERIC_KEYS = {"comparativa", "ausencias_en_el_periodo", "resumen"}
NOTE_KEYS = {"nota", "criterio", "mensaje", "nota_bajas", "persona_destacada"}


def _is_scalar(v: Any) -> bool:
    return v is not None and v != "" and not isinstance(v, dict | list)


def summary_view(
    summaries: list[dict[str, Any]],
    *,
    suppress_comparison: bool = False,
) -> dict[str, list[Any]]:
    """Del resumen de cada herramienta: tarjetas (cifras), comparativa (desgloses por tipo o por
    departamento), lectura contextual (desgloses simples y notas) y observaciones (avisos).

    suppress_comparison=True omite la generación automática de comparativas a partir de
    dict-of-dicts en los resúmenes (indicado para consultas operativas directas).
    """
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
            elif key in ("alertas_calidad", "advertencias") and isinstance(value, list):
                # Fase H: "advertencias" (privacidad/NOM-005, cobertura temporal, homogeneidad…) es la
                # clave real que usa analisis_economico_nominas y otras herramientas analíticas — antes
                # solo se reconocía "alertas_calidad", así que estos avisos nunca llegaban al 2D.
                quality += [str(_flat(a)) for a in value]
            elif _is_scalar(value) and isinstance(value, int | float) and not isinstance(value, bool):
                cards.append({"label": _label(key), "value": value})
            elif isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
                if not suppress_comparison:
                    # {tipo: {personas, periodos, dias}} → comparativa: una fila por métrica, una columna por tipo.
                    metrics = list(dict.fromkeys(m for v in value.values() for m in v))
                    comparison += [
                        {
                            "metrica": _label(m) if key in GENERIC_KEYS else f"{_label(key)} · {_label(m)}",
                            **{str(col): v.get(m) for col, v in value.items()},
                        }
                        for m in metrics
                        if all(_is_scalar(v.get(m)) or v.get(m) is None for v in value.values())
                    ]
            elif isinstance(value, dict) and value and all(_is_scalar(v) for v in value.values()):
                if "por_" in key or key.startswith("grupos"):
                    _chart_lbl = _label(
                        key[key.index("_por_") + 1 :] if "_por_" in key and not key.startswith("por_") else key
                    )
                    spec = chart_spec(_chart_lbl, [_chart_lbl, "Personas"], [[k, v] for k, v in value.items()])
                    if spec:
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
def mail_rows_view(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Formato del panel de correo del 2D (mail_rows / mail_summary), con la referencia de cada correo."""
    view = []
    for r in rows:
        name, address = sender_parts(r.get("from"))
        view.append(
            {
                "ref": r.get("ref"),
                "sender_name": name,
                "sender_address": address,
                "subject": r.get("subject"),
                "received_at": r.get("received_at"),
                "has_attachments": bool(r.get("has_attachments")),
                "preview": r.get("preview"),
                "no_reply": bool(r.get("no_reply")),
            }
        )
    return {
        "mail_rows": view,
        "mail_summary": {"mailbox": "Mi buzón", "total_unread": None, "total_conversations": len(view)},
    }


# ---------------------------------------------------------------------------------------- gráficos
def chart_from_table(view: dict[str, Any]) -> dict[str, Any] | None:
    """Gráfico de un recuento por categorías (tabla de dos columnas: categoría y cantidad)."""
    columns = [c["label"] for c in view.get("columns") or []]
    keys = [c["key"] for c in view.get("columns") or []]
    rows = [[r.get(k) for k in keys] for r in view.get("rows") or []]
    return chart_spec(view.get("title"), columns, rows)


def _absorb_report_preview(p: dict[str, Any], tables: list[dict[str, Any]], charts: list[dict[str, Any]]) -> None:
    """Adelanto ligero de un informe (``preview`` de ``persist_document_report``, ver
    ``mia.modules.rrhh.informes.persist``): reutiliza el mismo mecanismo ya existente de
    tablas/gráficos nativos del turno (``data["table"]``/``data["charts"]`` en ``legacy_view()``)
    en vez de inventar una clave nueva en el 2D -- nunca el informe entero, solo lo que el backend
    ya decidió mostrar como vista previa."""
    preview = p.get("preview")
    if not isinstance(preview, dict):
        return
    tables.extend(table_view(t) for t in preview.get("tables") or [] if isinstance(t, dict) and t.get("columns"))
    charts.extend(c for c in preview.get("charts") or [] if isinstance(c, dict))


def _absorb(
    p: dict[str, Any],
    data: dict[str, Any],
    actions: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    charts: list[dict[str, Any]],
) -> None:
    """Traduce una presentación de mIA a lo que pinta el 2D (tablas, tarjetas, acciones, correo…)."""
    kind = p.get("type")
    if p.get("documents"):
        data.setdefault("documents", []).extend(
            {k: d.get(k) for k in ("kind", "title", "subtitle", "date", "url")} for d in p["documents"][:36]
        )
    if kind == "employee_360":
        data["presentation"] = employee360_view(p)
    elif kind == "table" and p.get("mail_rows") is not None:
        data.update(mail_rows_view(p["mail_rows"]))
    elif kind == "calendar":
        data.setdefault("calendars", []).append(p)
    elif kind == "mail":
        data["mail_message"] = mail_message_view(p)
    elif kind == "mail_thread":
        rows = p.get("mail_rows") or []
        data.update(mail_rows_view(rows))
        data["mail_thread"] = {"title": p.get("title"), "count": len(rows)}
    elif kind == "mail_draft":
        data["mail_draft"] = {k: p.get(k) for k in ("borrador", "texto", "responde_a", "envio_habilitado")}
    elif kind == "news_list":
        # Rama propia (igual que el correo): sin ella, news_rows caía en el "else" genérico, que
        # la reconstruye como una tabla cruda sin formato (mia.modules.community.noticias.tools) — sin
        # enlaces clicables ni la tarjeta premium que sí entiende el panel de noticias del 2D.
        data["news_rows"] = p.get("news_rows") or []
    elif kind == "table":
        tables.append(table_view(p))
        # Fase H: los KPI y gráficos de primera clase que la herramienta YA calculó (p. ej.
        # analisis_economico_nominas) se perdían por completo — table_view() solo traduce columnas/
        # filas. Se priorizan sobre los derivados heurísticamente más abajo en legacy_view().
        cards.extend(kpis_to_cards(p.get("kpis")))
        if isinstance(p.get("charts"), list):
            charts.extend(c for c in p["charts"] if isinstance(c, dict))
        # Estadísticas de primera clase (p. ej. media/mediana/mínimo/máximo por departamento, ya
        # calculadas): se muestran como su propia tabla con nombre, nunca mezcladas en silencio con
        # la tabla principal ni descartadas.
        if isinstance(p.get("stats"), dict) and p["stats"].get("rows"):
            data["stats"] = table_view(p["stats"], "Estadísticas")
    elif kind == "dashboard":
        cards.extend(cards_from(p.get("kpis") or {}))
        tables.extend([table_view(t, "Panel") for t in p.get("tables") or [] if t.get("rows")])
    elif kind == "download" and p.get("url"):
        actions.append({"type": "download", "url": p["url"], "label": f"Descargar {p.get('format', 'informe')}"})
        _absorb_report_preview(p, tables, charts)
    elif kind == "downloads" and isinstance(p.get("items"), list):
        # Un informe pedido en varios formatos a la vez (p. ej. PDF + Excel): una acción de
        # descarga por formato, misma forma que el caso de un solo formato — el mundo 2D ya sabe
        # pintar varias acciones "download" sin necesitar un tipo de acción nuevo.
        actions.extend(
            {"type": "download", "url": item["url"], "label": f"Descargar {item.get('format', 'informe')}"}
            for item in p["items"]
            if isinstance(item, dict) and item.get("url")
        )
        _absorb_report_preview(p, tables, charts)
    elif kind == "job":
        # Fase H: trabajo en segundo plano (Job Manager) — paso directo de los campos que el mundo 2D
        # necesita para pintar la tarjeta y empezar a sondear su estado real; nunca se simula progreso
        # aquí, solo se transporta lo que el backend ya sabe en el momento de encolar.
        data["job"] = {k: p.get(k) for k in ("job_id", "kind", "status", "periodo", "formato")}
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


def _merge_same_schema_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combina tablas con esquema de columnas idéntico en una sola.

    Cuando el LLM llama a la misma herramienta varias veces (p.ej. turnos_dia por departamento),
    los resultados tienen el mismo esquema y deben mostrarse en una tabla unificada en lugar de
    quedar una oculta como tarjeta de contexto.
    """
    if len(tables) <= 1:
        return tables
    ref_cols = tuple(c["label"] for c in tables[0]["columns"])
    mergeable = [t for t in tables if tuple(c["label"] for c in t["columns"]) == ref_cols]
    other = [t for t in tables if tuple(c["label"] for c in t["columns"]) != ref_cols]
    if len(mergeable) <= 1:
        return tables
    all_rows = [row for t in mergeable for row in t["rows"]]
    # Título: prefijo común antes del separador " — " (p.ej. "Turnos 07/10/2026 — Restaurante" → "Turnos 07/10/2026")
    raw_titles = [t["title"] for t in mergeable]
    base = raw_titles[0].split(" — ")[0]
    shared_base = all(t.split(" — ")[0] == base for t in raw_titles)
    merged_title = base if shared_base and base != raw_titles[0] else raw_titles[0]
    merged = {**mergeable[0], "title": merged_title, "rows": all_rows, "total": len(all_rows)}
    return [merged] + other


def legacy_view(
    presentations: list[dict[str, Any]],
    summaries: list[dict[str, Any]] | None = None,
    *,
    suppress_comparison: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(data, actions) en el formato del 2D a partir de TODAS las presentaciones y resúmenes del turno."""
    data: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    native_charts: list[dict[str, Any]] = []
    calendar_tools = {"consulta_agenda", "detalle_reunion", "disponibilidad_agenda", "calendarios_disponibles",
                      "proponer_reunion", "ejecutar_propuesta_agenda", "preparar_reunion"}
    # Calendar counts/timestamps are not business KPI. Other domains retain their summaries.
    extra = summary_view(
        [item for item in summaries or [] if item.get("tool") not in calendar_tools],
        suppress_comparison=suppress_comparison,
    )
    for p in presentations:
        _absorb(p, data, actions, cards, tables, native_charts)
    tables = _merge_same_schema_tables(tables)
    every_table = list(tables)
    if tables:
        # El 2D pinta una tabla por respuesta: la más completa; el resto se ofrece como tarjeta de contexto.
        tables.sort(key=lambda t: (t["total"], len(t["columns"])), reverse=True)
        data["table"] = tables[0]
        cards += [{"label": t["title"], "value": t["total"], "unit": "registros"} for t in tables[1:]]
    _merge_extra(data, cards, extra)
    main = data.get("table")
    if main and main["columns"] and str(main["columns"][0]["label"]).lower() == "indicador":
        data.pop("comparacion", None)  # la tabla ya ES la comparativa: no se repite
    # Fase H: los gráficos de primera clase que la propia herramienta ya calculó (donut/bar/line
    # correctamente tipados, p. ej. analisis_economico_nominas) tienen prioridad sobre los derivados
    # heurísticamente de una tabla genérica de 2 columnas — nunca se recalculan ni se duplican.
    charts = native_charts[:3] or [c for t in every_table if (c := chart_from_table(t))][:2] or extra["charts"][:1]
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
