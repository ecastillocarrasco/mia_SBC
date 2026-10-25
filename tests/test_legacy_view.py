"""El 2D anterior pinta lo que mIA recupera: contrato de legacy_view con el código de mia-2d.js."""

from __future__ import annotations

from mia.api.legacy_view import legacy_view
from mia.conversation import ToolRegistry
from tests.test_domains import call, registry  # noqa: F401  (fixture)

TABLE = {
    "type": "table",
    "title": "Ausencias",
    "columns": ["Persona", "Departamento", "Tipo", "Desde", "Hasta", "Días", "Nota", "Vuelve"],
    "rows": [["Ana", "Pisos", "Baja/IT", "01/08/2026", "05/08/2026", 5, None, {"fecha": "2026-08-06"}]],
}


def test_table_has_keyed_columns_and_object_rows_with_all_columns() -> None:
    data, _ = legacy_view([TABLE])
    table = data["table"]
    # renderGenericTable filtra columnas sin «key» y lee row[c.key]: antes llegaban 0 columnas.
    assert [c["key"] for c in table["columns"]] == TABLE["columns"]
    assert table["rows"][0]["Persona"] == "Ana" and table["rows"][0]["Vuelve"] == "Fecha: 2026-08-06"
    assert len(table["columns"]) == 8  # sin recorte a 6 columnas


def test_no_visualizations_or_domain_that_would_hide_columns() -> None:
    data, _ = legacy_view([TABLE])
    assert "domain" not in data and "visualizations" not in data


def test_dashboard_becomes_cards_and_table() -> None:
    data, _ = legacy_view(
        [
            {
                "type": "dashboard",
                "title": "Panel",
                "kpis": {"plantilla_activa": 343, "trabajando": 139},
                "tables": [TABLE],
            }
        ]
    )
    assert {c["label"] for c in data["cards"]} == {"Plantilla activa", "Trabajando"}
    assert data["table"]["total"] == 1


def test_all_results_of_the_turn_are_used_not_only_the_first() -> None:
    small = {"type": "table", "title": "Búsqueda", "columns": ["Nombre"], "rows": [["Ana"]]}
    data, _ = legacy_view([small, TABLE])
    assert data["table"]["title"] == "Ausencias"  # la más completa
    assert any(c["label"] == "Búsqueda" for c in data["cards"])


def test_download_becomes_a_button() -> None:
    _, actions = legacy_view([{"type": "download", "url": "/api/reports/abc", "format": "pdf"}])
    assert actions == [{"type": "download", "url": "/api/reports/abc", "label": "Descargar pdf"}]


def test_several_formats_requested_at_once_become_one_button_each() -> None:
    """Pedir PDF + Excel en una sola llamada a generar_informe (``type == "downloads"``) debe dar
    exactamente el mismo resultado en el 2D que pedirlos uno a uno: una acción "download" por
    formato, mismo contrato de siempre (``mia-2d.js`` ya sabe pintar varias)."""
    _, actions = legacy_view([{
        "type": "downloads", "title": "Costes por departamento",
        "items": [
            {"url": "/api/reports/abc", "format": "pdf", "file_name": "Costes.pdf"},
            {"url": "/api/reports/def", "format": "xlsx", "file_name": "Costes.xlsx"},
        ],
    }])
    assert actions == [
        {"type": "download", "url": "/api/reports/abc", "label": "Descargar pdf"},
        {"type": "download", "url": "/api/reports/def", "label": "Descargar xlsx"},
    ]


def test_download_with_a_preview_also_fills_the_2d_table_and_charts() -> None:
    """La vista previa de un informe (``persist_document_report`` -> ``preview``) reutiliza el
    mecanismo ya existente de tabla/gráficos del turno en el 2D -- nunca una clave nueva que
    mia-2d.js tendría que aprender a leer."""
    data, actions = legacy_view([{
        "type": "download", "url": "/api/reports/abc", "format": "pdf", "title": "Comparativo Pisos",
        "preview": {
            "tables": [{"title": "Detalle", "columns": ["Nombre", "Horas"], "rows": [["Ana", 40], ["Luis", 38]]}],
            "charts": [{"type": "bar", "title": "Horas", "labels": ["Ana", "Luis"], "series": [{"name": "s", "values": [40, 38]}]}],
        },
    }])
    assert actions == [{"type": "download", "url": "/api/reports/abc", "label": "Descargar pdf"}]
    assert data["table"]["title"] == "Detalle"
    assert [c["label"] for c in data["table"]["columns"]] == ["Nombre", "Horas"]
    assert data["table"]["rows"] == [{"Nombre": "Ana", "Horas": 40}, {"Nombre": "Luis", "Horas": 38}]
    assert data["charts"][0]["type"] == "bar"


def test_download_without_a_preview_does_not_touch_table_or_charts() -> None:
    data, _ = legacy_view([{"type": "download", "url": "/api/reports/abc", "format": "pdf"}])
    assert "table" not in data
    assert "charts" not in data


async def test_real_employee360_uses_the_2d_schema(registry: ToolRegistry) -> None:  # noqa: F811
    result = await call(registry, "ficha_empleado", empleado_id=1, detalle=True)
    data, _ = legacy_view([result.presentation])
    p = data["presentation"]
    assert p["schema"] == "mia.employee360.presentation"
    ids = [s["id"] for s in p["sections"]]
    assert ids[:4] == ["hoy", "week", "next", "employment"] and "historico" in ids
    assert all({"FechaISO", "Turno"} <= set(d) for d in p["sections"][1]["items"])
    assert p["hero"]["title"] == "Ana Ruiz Sanz" and p["kpis"]


def test_tool_summaries_reach_the_screen() -> None:
    """Antes el resumen de cada herramienta (totales, desgloses, avisos) solo lo veía el modelo."""
    summary = {
        "personas_distintas": 42,
        "resumen_por_tipo": {"Baja/IT": {"personas": 17, "dias": 900}, "Vacaciones": {"personas": 27, "dias": 400}},
        "por_motivo": {"Vacaciones": 27, "Baja/IT": 17},
        "nota": "Una persona puede tener varias solicitudes.",
        "aviso": "Última sincronización hace 45 minutos: pueden faltar cambios recientes.",
        "regla": "interna",
    }
    data, _ = legacy_view([TABLE], [{"tool": "x", "summary": summary}])
    assert {"label": "Personas distintas", "value": 42} in data["cards"]
    assert {"metrica": "Resumen por tipo · Personas", "Baja/IT": 17, "Vacaciones": 27} in data["comparacion"]
    assert any(i.startswith("Por motivo: Vacaciones 27") for i in data["insights"])
    assert "Una persona puede tener varias solicitudes." in data["insights"]
    assert data["alertas_calidad"] == ["Última sincronización hace 45 minutos: pueden faltar cambios recientes."]
    assert not any("interna" in str(v) for v in data.values())


def test_counts_by_category_become_a_chart() -> None:
    """Enriquecer con gráficos: «número de empleados por departamento» es un recuento por categorías."""
    table = {
        "type": "table",
        "title": "Por departamento",
        "columns": ["Departamento", "Personas"],
        "rows": [
            ["Pisos", 136],
            ["Restaurante", 71],
            ["Cocina", 43],
            ["Animación", 20],
            ["Recepción", 20],
            ["Mantenimiento", 14],
            ["Supermercado", 13],
        ],
    }
    data, _ = legacy_view([table])
    chart = data["charts"][0]
    assert chart["type"] == "bar" and chart["labels"][0] == "Pisos" and chart["series"][0]["values"][0] == 136
    few, _ = legacy_view([{**table, "rows": table["rows"][:3]}])
    assert few["charts"][0]["type"] == "donut"  # pocas categorías: partes de un todo
    months = {
        "type": "table",
        "title": "Nóminas por mes",
        "columns": ["Mes", "Documentos"],
        "rows": [["2026-05", 40], ["2026-06", 41], ["2026-07", 43]],
    }
    assert legacy_view([months])[0]["charts"][0]["type"] == "line"


def test_no_chart_for_lists_indicators_or_mixed_values() -> None:
    people = {
        "type": "table",
        "title": "Edad",
        "columns": ["Persona", "Edad"],
        "rows": [[f"P{i}", 30 + i] for i in range(40)],
    }
    kpis = {
        "type": "table",
        "title": "Departamento",
        "columns": ["Indicador", "Valor"],
        "rows": [["Plantilla", 136], ["Trabajando", 55], ["Baja", 16]],
    }
    assert "charts" not in legacy_view([people])[0] and "charts" not in legacy_view([kpis])[0]


def test_mail_is_translated_to_the_mail_panel_with_refs() -> None:
    listing = {
        "type": "table",
        "title": "Correos sin leer",
        "columns": ["Ref", "De", "Asunto", "Recibido"],
        "rows": [["c1", "Ana <a@x.com>", "Hola", "2026-08-22T13:35:11Z"]],
        "mail_rows": [
            {
                "ref": "c1",
                "from": "Ana <a@x.com>",
                "subject": "Hola",
                "received_at": "2026-08-22T13:35:11Z",
                "has_attachments": False,
            }
        ],
    }
    data, _ = legacy_view([listing])
    row = data["mail_rows"][0]
    assert row["ref"] == "c1" and row["sender_name"] == "Ana" and row["sender_address"] == "a@x.com"
    assert "table" not in data  # el panel de correo sustituye a la tabla genérica
    draft, _ = legacy_view(
        [{"type": "mail_draft", "borrador": "b1", "texto": "Gracias", "responde_a": "c1", "envio_habilitado": False}]
    )
    assert draft["mail_draft"]["borrador"] == "b1" and draft["mail_draft"]["envio_habilitado"] is False
    opened, _ = legacy_view(
        [
            {
                "type": "mail",
                "ref": "c1",
                "de": "Ana <a@x.com>",
                "asunto": "Hola",
                "texto": "Cuerpo",
                "adjuntos": ["a.pdf"],
            }
        ]
    )
    assert opened["mail_message"]["text"] == "Cuerpo" and opened["mail_message"]["attachments"] == ["a.pdf"]
    thread, _ = legacy_view(
        [
            {
                "type": "mail_thread",
                "title": "Hilo: Hola",
                "columns": ["Ref", "De", "Asunto", "Recibido"],
                "rows": [["c1", "Ana <a@x.com>", "Hola", "2026-08-22T13:35:11Z"]],
                "mail_rows": [
                    {
                        "ref": "c1",
                        "from": "Ana <a@x.com>",
                        "subject": "Hola",
                        "received_at": "2026-08-22T13:35:11Z",
                        "has_attachments": False,
                    },
                    {
                        "ref": "c2",
                        "from": "RRHH <rrhh@x.com>",
                        "subject": "Re: Hola",
                        "received_at": "2026-08-23T09:00:00Z",
                        "has_attachments": True,
                    },
                ],
            }
        ]
    )
    assert thread["mail_thread"] == {"title": "Hilo: Hola", "count": 2}
    assert len(thread["mail_rows"]) == 2
    assert thread["mail_rows"][1]["sender_name"] == "RRHH"
    assert "table" not in thread  # el hilo también sustituye a la tabla genérica, no se duplica


def test_news_list_is_translated_to_the_news_panel_not_a_generic_table() -> None:
    """Regresión de producción: sin su propia rama, ``news_list`` caía en el ``else`` genérico de
    ``_absorb()``, que reconstruía ``news_rows`` como una tabla cruda sin formato ("News rows" /
    "Información estructurada") — sin enlaces clicables ni la tarjeta premium del panel del 2D, y
    con el turno clasificado como "analítica" en vez de "noticias"."""
    presentation = {
        "type": "news_list",
        "title": "Noticias corporativas y del grupo",
        "columns": ["Título", "Empresa", "Categoría", "Fuente", "Fecha"],
        "rows": [["FBD Hotels adquiere un hotel", "Grupo FBD", "Hotelera / turismo", "Irish Times", "20/10/2026"]],
        "news_rows": [
            {
                "titulo": "FBD Hotels adquiere un hotel",
                "fuente": "Irish Times",
                "empresa": "Grupo FBD",
                "categoria": "Hotelera / turismo",
                "fecha": "20/10/2026",
                "resumen": None,
                "url": "https://news.google.com/rss/articles/AAAA",
            }
        ],
    }
    data, _ = legacy_view([presentation])
    assert data["news_rows"] == presentation["news_rows"]
    assert "table" not in data  # el panel de noticias sustituye a la tabla genérica, no se duplica


def test_headcount_by_department_from_the_tool_summary_becomes_a_chart() -> None:
    """Caso real: «empleados por departamento» llegó como listado de 343 personas + resumen; sin gráfico."""
    grouped = {
        "Pisos": 136,
        "Restaurante": 71,
        "Cocina": 43,
        "Animación": 20,
        "Recepción": 20,
        "Mantenimiento": 14,
        "Supermercado": 13,
        "RRHH": 6,
    }
    people = {
        "type": "table",
        "title": "Plantilla",
        "columns": ["Nombre", "Departamento", "Puesto"],
        "rows": [[f"P{i}", "Pisos", "X"] for i in range(30)],
    }
    data, _ = legacy_view([people], [{"tool": "plantilla", "summary": {"total": 30, "por_departamento": grouped}}])
    chart = data["charts"][0]
    assert chart["type"] == "bar" and chart["labels"][:2] == ["Pisos", "Restaurante"]


def test_labels_have_their_accents_and_the_card_order_is_stable() -> None:
    from mia.api.legacy_view import employee360_view  # noqa: PLC0415

    card = {
        "nombre": "Sandra",
        "activo": True,
        "indicadores": {
            "documentos_firmados": 17,
            "nominas_no_leidas": 7,
            "saldo_vacaciones": 0.0,
            "dias_de_baja_este_anio": 0,
        },
        "vacaciones": {"pendientes": 0, "saldo_total": 24.0, "saldo_actual": 0.0},
        "ficha_laboral": {"telefono": "635", "codigo_empleado": "303"},
        "proximos_hitos": [{"hito": "próximo descanso", "fecha": "2026-10-03"}],
    }
    view = employee360_view(card)
    assert [k["label"] for k in view["kpis"]] == [
        "Saldo vacaciones",
        "Días de baja este año",
        "Nóminas no leídas",
        "Documentos firmados",
    ]
    sections = {s["id"]: s for s in view["sections"]}
    assert list(sections["vacaciones"]["data"]) == ["saldo_actual", "saldo_total", "pendientes"]
    assert sections["next"]["items"][0]["display_date"] == "sáb 03/10/2026"
    from mia.text import humanize_label  # noqa: PLC0415

    assert humanize_label("codigo_empleado") == "Código empleado"


# ──────────────────────────────────────────────── Fase H: KPI/gráficos de primera clase, advertencias


ECONOMIC_TABLE = {
    "type": "table",
    "title": "Gasto salarial por departamento · Agosto 2026 (Coste empresa)",
    "columns": ["Departamento", "Agosto 2026", "Total", "Peso %"],
    "rows": [["Cocina", "6.990,45", "6.990,45", "44,3%"], ["Recepción", "8.790,45", "8.790,45", "55,7%"]],
    "kpis": [
        {"label": "Gasto total del periodo", "value": "15.780,90 €", "highlight": True},
        {"label": "Agosto 2026", "value": "15.780,90 €"},
    ],
    "charts": [
        {
            "type": "donut",
            "title": "Distribución del gasto · Agosto 2026",
            "labels": ["Cocina", "Recepción"],
            "series": [{"name": "Coste empresa", "values": [6990.45, 8790.45]}],
        },
        {
            "type": "bar",
            "title": "Ranking de gasto salarial · Agosto 2026",
            "labels": ["Recepción", "Cocina"],
            "series": [{"name": "Coste empresa", "values": [8790.45, 6990.45]}],
        },
    ],
}


def test_table_kpis_reach_the_screen_as_cards() -> None:
    """Fase H: antes, los KPI de primera clase de una tabla (p. ej. analisis_economico_nominas) se
    perdían por completo — `table_view()` solo traduce columnas/filas, nunca `kpis`."""
    data, _ = legacy_view([ECONOMIC_TABLE])
    labels = [c["label"] for c in data["cards"]]
    assert "Gasto total del periodo" in labels


def test_table_native_charts_take_priority_over_the_derived_heuristic() -> None:
    """Fase H: los gráficos ya calculados por la herramienta (correctamente tipados: donut/bar) deben
    usarse tal cual, en vez de derivar uno genérico de 2 columnas desde la tabla final."""
    data, _ = legacy_view([ECONOMIC_TABLE])
    assert data["charts"][0]["type"] == "donut"
    assert data["charts"][0]["labels"] == ["Cocina", "Recepción"]
    assert len(data["charts"]) == 2


def test_advertencias_in_a_tool_summary_reach_alertas_calidad() -> None:
    """Fase H: `analisis_economico_nominas` (y otras herramientas analíticas) usan la clave
    `advertencias` en su resumen — antes `summary_view()` solo reconocía `alertas_calidad`, así que
    los avisos de k-anonimato/cobertura nunca llegaban a la pantalla."""
    summaries = [
        {
            "summary": {
                "advertencias": [
                    "1 departamento(s) no cumplen el mínimo de 3 personas y no se desglosan "
                    "(protección de datos, NOM-005)."
                ]
            }
        }
    ]
    data, _ = legacy_view([ECONOMIC_TABLE], summaries)
    assert any("NOM-005" in a for a in data["alertas_calidad"])


def test_table_stats_reach_the_screen_as_their_own_named_block() -> None:
    """Fase H, revisión de completitud: 'Estadísticas' de primera clase (p. ej. media/mediana/mínimo/
    máximo por departamento) no deben perderse en silencio ni mezclarse con la tabla principal."""
    with_stats = {
        **ECONOMIC_TABLE,
        "stats": {
            "type": "table",
            "title": "Estadísticas salariales",
            "columns": ["Departamento", "Media"],
            "rows": [["Cocina", "2.330,15"], ["Recepción", "2.930,15"]],
        },
    }
    data, _ = legacy_view([with_stats])
    assert data["stats"]["title"] == "Estadísticas salariales"
    assert data["stats"]["subtitle"] == "Estadísticas"
    assert data["stats"]["rows"][0]["Departamento"] == "Cocina"
    # Nunca se mezcla con la tabla principal: siguen siendo bloques separados.
    assert data["table"]["title"] != data["stats"]["title"]


def test_job_presentation_passes_through_for_the_2d_job_card() -> None:
    """Fase H, "integración del Job Manager en el mundo 2D real": el 2D necesita job_id/status/periodo
    para pintar la tarjeta y empezar a sondear — nunca se simula el progreso aquí."""
    job_presentation = {
        "type": "job",
        "job_id": "abc123",
        "kind": "informe_economico_nominas",
        "status": "queued",
        "periodo": "agosto de 2026",
        "formato": "pdf",
    }
    data, _ = legacy_view([job_presentation])
    assert data["job"] == {
        "job_id": "abc123",
        "kind": "informe_economico_nominas",
        "status": "queued",
        "periodo": "agosto de 2026",
        "formato": "pdf",
    }
