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
