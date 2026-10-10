"""mia.analytics — StatisticsEngine, InsightEngine, ComparisonEngine.

Capa analítica (FASE B de la expansión funcional): cálculos deterministas en
Python puro, sin BD ni LLM. Estas tools ya están cableadas en producción
conversacional vía modules/rrhh/analitica/universal.py; esta batería cubre
los módulos de analytics/ de forma aislada.
"""

from __future__ import annotations

from mia.analytics.comparison import ComparisonResult, MetricComparison, MultiGroupComparison
from mia.analytics.insights import InsightEngine
from mia.analytics.stats import (
    TimePoint,
    descriptive,
    detect_abrupt_changes,
    detect_outliers,
    frequency_distribution,
    time_series_stats,
)


# ------------------------------------------------------------------ descriptive
def test_descriptive_basic_stats() -> None:
    out = descriptive([10.0, 20.0, 30.0, 40.0])
    assert out["count"] == 4
    assert out["mean"] == 25.0
    assert out["median"] == 25.0
    assert out["min"] == 10.0
    assert out["max"] == 40.0
    assert out["range"] == 30.0


def test_descriptive_ignores_none_and_nan() -> None:
    out = descriptive([10.0, None, 20.0])
    assert out["count"] == 2


def test_descriptive_empty_list_reports_zero_count() -> None:
    out = descriptive([])
    assert out["count"] == 0
    assert "nota" in out


def test_descriptive_percentiles_only_with_enough_samples() -> None:
    small = descriptive([1.0, 2.0, 3.0])
    assert "p25" not in small
    big = descriptive([1.0, 2.0, 3.0, 4.0, 5.0])
    assert "p25" in big


def test_descriptive_mode_only_reported_when_there_are_duplicates() -> None:
    no_dupes = descriptive([1.0, 2.0, 3.0])
    assert "mode" not in no_dupes
    with_dupes = descriptive([1.0, 1.0, 2.0])
    assert with_dupes["mode"] == 1.0
    assert with_dupes["mode_freq"] == 2


# ------------------------------------------------------------------ frequency_distribution
def test_frequency_distribution_counts_and_percentages() -> None:
    out = frequency_distribution(["IT", "IT", "Ventas"])
    assert out["total"] == 3
    assert out["unique"] == 2
    top = {d["value"]: d["pct"] for d in out["distribution"]}
    assert top["IT"] == 66.67


def test_frequency_distribution_empty_input() -> None:
    out = frequency_distribution([])
    assert out["total"] == 0
    assert out["distribution"] == []


# ------------------------------------------------------------------ time_series_stats
def _series(values: list[float]) -> list[TimePoint]:
    return [TimePoint(label=f"m{i}", value=v) for i, v in enumerate(values)]


def test_time_series_stats_reports_first_last_min_max() -> None:
    out = time_series_stats(_series([10.0, 30.0, 20.0]))
    assert out["first"]["value"] == 10.0
    assert out["last"]["value"] == 20.0
    assert out["max"]["value"] == 30.0
    assert out["min"]["value"] == 10.0


def test_time_series_stats_total_change_direction() -> None:
    out = time_series_stats(_series([100.0, 150.0]))
    assert out["total_change"]["direction"] == "up"
    assert out["total_change"]["pct"] == 50.0


def test_time_series_stats_trend_requires_three_points() -> None:
    short = time_series_stats(_series([1.0, 2.0]))
    assert "trend" not in short
    rising = time_series_stats(_series([1.0, 2.0, 3.0, 4.0]))
    assert rising["trend"]["direction"] == "increasing"


def test_time_series_stats_empty_points() -> None:
    out = time_series_stats([])
    assert out["count"] == 0


def test_time_series_stats_ignores_none_values() -> None:
    points = [TimePoint("a", 10.0), TimePoint("b", None), TimePoint("c", 20.0)]
    out = time_series_stats(points)
    assert out["count"] == 2


# ------------------------------------------------------------------ outliers
def test_detect_outliers_iqr_flags_extreme_value() -> None:
    values = [10.0, 11.0, 9.0, 10.5, 9.5, 100.0]
    out = detect_outliers(values, method="iqr")
    flagged = {o["value"] for o in out["outliers"]}
    assert 100.0 in flagged


def test_detect_outliers_insufficient_sample_returns_empty() -> None:
    out = detect_outliers([1.0, 2.0])
    assert out["outliers"] == []


def test_detect_abrupt_changes_above_threshold() -> None:
    points = _series([100.0, 105.0, 200.0])
    changes = detect_abrupt_changes(points, threshold_pct=30.0)
    assert len(changes) == 1
    assert changes[0]["direction"] == "up"


def test_detect_abrupt_changes_below_threshold_is_empty() -> None:
    points = _series([100.0, 105.0, 110.0])
    assert detect_abrupt_changes(points, threshold_pct=30.0) == []


# ------------------------------------------------------------------ InsightEngine
def test_insight_engine_from_time_series_detects_growth() -> None:
    engine = InsightEngine()
    points = _series([100.0, 110.0, 160.0])
    insights = engine.from_time_series(points, label="absentismo", unit="días")
    assert any(i.type in ("trend_up", "highest_increase") for i in insights)


def test_insight_engine_from_time_series_short_series_returns_empty() -> None:
    engine = InsightEngine()
    assert engine.from_time_series(_series([1.0]), label="x") == []


def test_insight_engine_from_distribution_identifies_leader_and_laggard() -> None:
    engine = InsightEngine()
    insights = engine.from_distribution({"Cocina": 40.0, "Pisos": 10.0, "Recepción": 5.0}, metric="ausencias")
    types = {i.type for i in insights}
    assert "max_value" in types
    assert "min_value" in types


def test_insight_engine_from_distribution_flags_concentration() -> None:
    engine = InsightEngine()
    insights = engine.from_distribution({"A": 90.0, "B": 10.0}, metric="coste")
    assert any(i.type == "concentration" for i in insights)


def test_insight_engine_from_comparison_names_the_winner() -> None:
    engine = InsightEngine()
    insights = engine.from_comparison("IT", 40000.0, "Ventas", 30000.0, metric="salario medio", unit="€")
    assert len(insights) == 1
    assert "IT" in insights[0].text


def test_insight_engine_top_insights_respects_limit_and_order() -> None:
    engine = InsightEngine()
    points = _series([100.0, 50.0, 500.0, 10.0])
    insights = engine.from_time_series(points, label="x")
    top = engine.top_insights(insights, n=2)
    assert len(top) <= 2
    if len(top) == 2:
        assert top[0]["importance"] >= top[1]["importance"]


# ------------------------------------------------------------------ ComparisonEngine
def test_metric_comparison_computes_diff_and_winner() -> None:
    m = MetricComparison("Salario medio", "IT", 40000.0, "Ventas", 30000.0, unit="€", higher_is_better=True)
    assert m.absolute_diff == 10000.0
    assert m.winner == "IT"


def test_metric_comparison_lower_is_better_flips_winner() -> None:
    m = MetricComparison("Absentismo", "IT", 2.0, "Ventas", 5.0, unit="%", higher_is_better=False)
    assert m.winner == "IT"


def test_metric_comparison_neutral_has_no_winner() -> None:
    m = MetricComparison("Antigüedad", "IT", 5.0, "Ventas", 3.0, higher_is_better=None)
    assert m.winner is None


def test_metric_comparison_missing_value_yields_none_diffs() -> None:
    m = MetricComparison("X", "A", None, "B", 10.0)
    assert m.absolute_diff is None
    assert m.pct_diff is None
    assert m.winner is None


def test_comparison_result_to_table_and_key_insights() -> None:
    result = ComparisonResult(
        "IT", "Ventas",
        metrics=[MetricComparison("Salario medio", "IT", 40000.0, "Ventas", 30000.0, unit="€", higher_is_better=True)],
    )
    table = result.to_table()
    assert table["type"] == "table"
    assert "IT" in table["columns"]
    insights = result.key_insights()
    assert insights and "IT" in insights[0]


def test_multi_group_comparison_ranking_orders_descending_by_default() -> None:
    comp = MultiGroupComparison(groups={"A": {"m": 10.0}, "B": {"m": 30.0}, "C": {"m": 20.0}})
    ranking = comp.ranking("m")
    assert [r["group"] for r in ranking] == ["B", "C", "A"]


def test_multi_group_comparison_to_table_picks_best_and_worst() -> None:
    comp = MultiGroupComparison(
        groups={"A": {"ausencias": 10.0}, "B": {"ausencias": 2.0}},
        metric_higher_is_better={"ausencias": False},
    )
    table = comp.to_table()
    row = table["rows"][0]
    assert row[-2] == "B"  # mejor: menos ausencias
    assert row[-1] == "A"  # peor
