"""``_build_preview`` (mia.modules.rrhh.informes.persist): el adelanto ligero de un documento que
viaja en ``presentation["preview"]`` para que 2D/3D puedan mostrar algo más rico que un recuento de
secciones -- nunca el informe completo, que solo se entrega como fichero descargable."""

from __future__ import annotations

from mia.modules.rrhh.informes.persist import (
    _PREVIEW_MAX_CHARTS,
    _PREVIEW_MAX_TABLE_ROWS,
    _PREVIEW_MAX_TABLES,
    _build_preview,
)
from mia.reporting.document import Block, Document


def _table(title: str, rows: int) -> Block:
    return Block("table", title, {"columns": ["Nombre", "Valor"], "rows": [[f"fila {i}", i] for i in range(rows)]})


def test_no_table_or_chart_blocks_returns_none() -> None:
    doc = Document("Informe", blocks=[Block("narrative", "Resumen", {"statements": []})])
    assert _build_preview(doc) is None


def test_kpis_and_annex_blocks_are_never_included() -> None:
    """Los KPIs ya tienen su propio formato compacto (Holograma); un anexo es detalle a granel, no
    una vista previa -- ninguno de los dos debe colarse en preview["tables"]/preview["charts"]."""
    doc = Document(
        "Informe",
        blocks=[
            Block("kpis", "Indicadores", {"Total": "10"}),
            Block(
                "annex", "Detalle completo", {"columns": ["A"], "rows": [["x"]], "total_rows": 1, "truncated": False}
            ),
        ],
    )
    assert _build_preview(doc) is None


def test_table_rows_are_capped_and_the_truncation_is_explicit() -> None:
    doc = Document("Informe", blocks=[_table("Empleados", _PREVIEW_MAX_TABLE_ROWS + 5)])
    preview = _build_preview(doc)
    table = preview["tables"][0]
    assert len(table["rows"]) == _PREVIEW_MAX_TABLE_ROWS
    assert table["total_rows"] == _PREVIEW_MAX_TABLE_ROWS + 5
    assert table["truncated"] is True


def test_table_not_truncated_when_it_fits() -> None:
    doc = Document("Informe", blocks=[_table("Empleados", 3)])
    table = _build_preview(doc)["tables"][0]
    assert len(table["rows"]) == 3
    assert table["total_rows"] == 3
    assert table["truncated"] is False


def test_empty_table_block_is_skipped() -> None:
    """Una tabla sin filas (o sin columnas) no aporta nada a la vista previa."""
    doc = Document("Informe", blocks=[Block("table", "Vacía", {"columns": ["A"], "rows": []})])
    assert _build_preview(doc) is None


def test_number_of_tables_and_charts_is_capped() -> None:
    blocks = [_table(f"Tabla {i}", 2) for i in range(_PREVIEW_MAX_TABLES + 3)]
    blocks += [
        Block("chart", f"Gráfico {i}", {"type": "bar", "labels": ["a"], "series": [{"name": "s", "values": [1]}]})
        for i in range(_PREVIEW_MAX_CHARTS + 3)
    ]
    preview = _build_preview(Document("Informe", blocks=blocks))
    assert len(preview["tables"]) == _PREVIEW_MAX_TABLES
    assert len(preview["charts"]) == _PREVIEW_MAX_CHARTS


def test_chart_block_data_is_passed_through_unmodified() -> None:
    spec = {"type": "donut", "title": "Reparto", "labels": ["A", "B"], "series": [{"name": "s", "values": [3, 7]}]}
    doc = Document("Informe", blocks=[Block("chart", "Reparto", spec)])
    preview = _build_preview(doc)
    assert preview["charts"][0] == spec


def test_chart_block_with_no_data_is_skipped() -> None:
    doc = Document("Informe", blocks=[Block("chart", "Vacío", {})])
    assert _build_preview(doc) is None
