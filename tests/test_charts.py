"""modules.rrhh.charts — selección automática y construcción de gráficos.

chart_spec() es la entrada histórica (tablas de 2 columnas); esta batería
fija su comportamiento y cubre las funciones nuevas de la expansión
funcional (chart_spec_multi, select_chart_type, histogram_chart,
scatter_chart, grouped_bar_chart) para que una regresión en la selección de
tipo de gráfico se detecte aquí, no en producción.
"""

from __future__ import annotations

from mia.modules.rrhh.charts import (
    NOT_CHARTABLE_HEADERS,
    chart_spec,
    chart_spec_multi,
    grouped_bar_chart,
    histogram_chart,
    scatter_chart,
    select_chart_type,
    to_number,
)


# ------------------------------------------------------------------ chart_spec (2 columnas, compat)
def test_chart_spec_two_columns_few_rows_is_donut() -> None:
    spec = chart_spec("Plantilla", ["Departamento", "Personas"], [["IT", 10], ["Ventas", 5]])
    assert spec is not None
    assert spec["type"] == "donut"
    assert spec["labels"] == ["IT", "Ventas"]
    assert spec["series"][0]["values"] == [10.0, 5.0]


def test_chart_spec_two_columns_many_rows_is_bar() -> None:
    rows = [[f"Dept{i}", i + 1] for i in range(8)]
    spec = chart_spec("Plantilla", ["Departamento", "Personas"], rows)
    assert spec is not None
    assert spec["type"] == "bar"


def test_chart_spec_time_like_labels_is_line() -> None:
    rows = [["2025-01", 10], ["2025-02", 20], ["2025-03", 15]]
    spec = chart_spec("Serie", ["Mes", "Ausencias"], rows)
    assert spec is not None
    assert spec["type"] == "line"


def test_chart_spec_returns_none_for_too_few_rows() -> None:
    assert chart_spec("X", ["A", "B"], [["a", 1]]) is None


def test_chart_spec_returns_none_for_too_many_rows() -> None:
    rows = [[f"r{i}", i] for i in range(30)]
    assert chart_spec("X", ["A", "B"], rows) is None


def test_chart_spec_returns_none_when_values_not_numeric() -> None:
    rows = [["a", "n/d"], ["b", "n/d"]]
    assert chart_spec("X", ["A", "B"], rows) is None


def test_chart_spec_returns_none_for_duplicate_labels() -> None:
    rows = [["IT", 10], ["IT", 20]]
    assert chart_spec("X", ["Departamento", "Personas"], rows) is None


def test_chart_spec_returns_none_for_not_chartable_header() -> None:
    header = next(iter(NOT_CHARTABLE_HEADERS))
    rows = [["a", 1], ["b", 2]]
    assert chart_spec("X", [header, "Valor"], rows) is None


def test_chart_spec_returns_none_for_department_sheet_title() -> None:
    rows = [["a", 1], ["b", 2]]
    assert chart_spec("Departamento · Cocina", ["A", "B"], rows) is None


# ------------------------------------------------------------------ chart_spec_multi (3+ columnas)
def test_chart_spec_multi_non_temporal_is_grouped_bar() -> None:
    rows = [["IT", 10, 5], ["Ventas", 20, 8]]
    spec = chart_spec_multi("Comparativa", ["Departamento", "Ausencias", "Bajas"], rows)
    assert spec is not None
    assert spec["type"] == "grouped_bar"
    assert len(spec["series"]) == 2


def test_chart_spec_multi_temporal_labels_is_line() -> None:
    rows = [["2025-01", 10, 5], ["2025-02", 20, 8]]
    spec = chart_spec_multi("Tendencia", ["Mes", "Año actual", "Año anterior"], rows)
    assert spec is not None
    assert spec["type"] == "line"


def test_chart_spec_multi_drops_non_numeric_series() -> None:
    rows = [["IT", 10, "n/d"], ["Ventas", 20, "n/d"]]
    spec = chart_spec_multi("X", ["Departamento", "Ausencias", "Notas"], rows)
    assert spec is not None
    assert len(spec["series"]) == 1


def test_chart_spec_multi_requires_at_least_three_columns() -> None:
    assert chart_spec_multi("X", ["A", "B"], [["a", 1], ["b", 2]]) is None


# ------------------------------------------------------------------ select_chart_type
def test_select_chart_type_distribution_hint_is_histogram() -> None:
    assert select_chart_type(["a", "b"], hint="distribution") == "histogram"


def test_select_chart_type_correlation_hint_is_scatter() -> None:
    assert select_chart_type(["a", "b"], hint="correlation") == "scatter"


def test_select_chart_type_ranking_hint_is_horizontal_bar() -> None:
    assert select_chart_type(["a", "b", "c"], hint="ranking") == "horizontal_bar"


def test_select_chart_type_many_non_temporal_labels_is_horizontal_bar() -> None:
    labels = [f"p{i}" for i in range(15)]
    assert select_chart_type(labels) == "horizontal_bar"


def test_select_chart_type_temporal_labels_is_line_even_with_hint_absent() -> None:
    assert select_chart_type(["2025-01", "2025-02", "2025-03"]) == "line"


def test_select_chart_type_composition_hint_few_labels_is_donut() -> None:
    assert select_chart_type(["a", "b", "c"], hint="composition") == "donut"


def test_select_chart_type_composition_hint_many_labels_is_stacked_bar() -> None:
    labels = [f"g{i}" for i in range(10)]
    assert select_chart_type(labels, hint="composition") == "stacked_bar"


def test_select_chart_type_multi_series_non_temporal_is_grouped_bar() -> None:
    assert select_chart_type(["a", "b", "c"], num_series=2) == "grouped_bar"


def test_select_chart_type_single_series_few_labels_is_donut() -> None:
    assert select_chart_type(["a", "b"], num_series=1) == "donut"


def test_select_chart_type_single_series_many_labels_is_bar() -> None:
    labels = [f"g{i}" for i in range(10)]
    assert select_chart_type(labels, num_series=1) == "bar"


# ------------------------------------------------------------------ constructores específicos
def test_histogram_chart_buckets_values_into_requested_bins() -> None:
    spec = histogram_chart("Distribución", [1.0, 2.0, 3.0, 4.0, 5.0], bins=5)
    assert spec["type"] == "histogram"
    assert len(spec["labels"]) == 5
    assert sum(spec["series"][0]["values"]) == 5


def test_histogram_chart_handles_constant_values() -> None:
    spec = histogram_chart("Constante", [7.0, 7.0, 7.0])
    assert spec["series"][0]["values"] == [3.0]


def test_histogram_chart_empty_values() -> None:
    spec = histogram_chart("Vacío", [])
    assert spec["labels"] == []
    assert spec["series"] == []


def test_scatter_chart_pairs_x_and_y() -> None:
    spec = scatter_chart("Correlación", [1.0, 2.0, 3.0], [10.0, 20.0, 30.0], x_label="Edad", y_label="Salario")
    assert spec["type"] == "scatter"
    assert spec["series"][0]["x"] == [1.0, 2.0, 3.0]
    assert spec["series"][0]["values"] == [10.0, 20.0, 30.0]


def test_grouped_bar_chart_keeps_all_series() -> None:
    series = [{"name": "2024", "values": [1.0, 2.0]}, {"name": "2025", "values": [3.0, 4.0]}]
    spec = grouped_bar_chart("Comparativa", ["Ene", "Feb"], series)
    assert spec["type"] == "grouped_bar"
    assert spec["series"] == series


# ------------------------------------------------------------------ to_number
def test_to_number_parses_spanish_decimal_format() -> None:
    assert to_number("1.234,56") == 1234.56


def test_to_number_parses_negative_integer() -> None:
    assert to_number("-42") == -42.0


def test_to_number_returns_none_for_non_numeric_text() -> None:
    assert to_number("n/d") is None


def test_to_number_returns_none_for_bool() -> None:
    assert to_number(True) is None
