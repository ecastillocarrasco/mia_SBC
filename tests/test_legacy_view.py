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
