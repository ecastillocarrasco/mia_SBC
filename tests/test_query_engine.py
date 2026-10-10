"""mia.query — NormalizedDataset, UniversalQueryEngine, PeriodEngine, SemanticFieldRegistry.

Capa de consulta universal (FASE A de la expansión funcional): ninguna tool
la invoca todavía (ver FUNCTIONAL_EXPANSION/02_UNIVERSAL_QUERY_ENGINE.md),
así que su única cobertura hoy es esta batería directa sobre los módulos.
"""

from __future__ import annotations

from datetime import date

from mia.query.dataset import NormalizedDataset
from mia.query.engine import AggSpec, FilterClause, UniversalQueryEngine
from mia.query.fields import field_registry
from mia.query.period import PeriodEngine

ENGINE = UniversalQueryEngine()


def _employees() -> NormalizedDataset:
    rows = [
        {"name": "Ana", "department": "IT", "salary": 32000.0, "years": 6},
        {"name": "Luis", "department": "IT", "salary": 28000.0, "years": 2},
        {"name": "Marta", "department": "Ventas", "salary": 26000.0, "years": 4},
        {"name": "Pedro", "department": "Ventas", "salary": 41000.0, "years": 9},
    ]
    return NormalizedDataset.from_dicts("Empleados", rows)


# ------------------------------------------------------------------ NormalizedDataset
def test_from_dicts_infers_schema_types() -> None:
    ds = _employees()
    types = {s.name: s.type for s in ds.schema}
    assert types["name"] == "string"
    assert types["salary"] == "float"
    assert types["years"] == "int"


def test_to_presentation_matches_frontend_table_contract() -> None:
    ds = _employees()
    pres = ds.to_presentation()
    assert pres["type"] == "table"
    assert pres["columns"] == ds.column_labels()
    assert len(pres["rows"]) == 4
    assert pres["truncated"] is False


def test_numeric_column_ignores_non_numeric_and_none() -> None:
    ds = NormalizedDataset.from_dicts("Mixto", [{"v": 1}, {"v": None}, {"v": "x"}, {"v": 2.5}])
    assert ds.numeric_column("v") == [1.0, 2.5]


def test_clone_with_does_not_mutate_original() -> None:
    ds = _employees()
    clone = ds.clone_with(rows=ds.rows[:1])
    assert len(ds.rows) == 4
    assert len(clone.rows) == 1


# ------------------------------------------------------------------ filter
def test_filter_eq_is_case_insensitive_for_strings() -> None:
    ds = ENGINE.filter(_employees(), [FilterClause("department", "eq", "it")])
    assert {r["name"] for r in ds.rows} == {"Ana", "Luis"}


def test_filter_gte_numeric() -> None:
    ds = ENGINE.filter(_employees(), [FilterClause("salary", "gte", 30000)])
    assert {r["name"] for r in ds.rows} == {"Ana", "Pedro"}


def test_filter_multiple_clauses_are_anded() -> None:
    ds = ENGINE.filter(
        _employees(),
        [FilterClause("department", "eq", "Ventas"), FilterClause("years", "gt", 5)],
    )
    assert [r["name"] for r in ds.rows] == ["Pedro"]


def test_filter_is_null_and_not_null() -> None:
    ds = NormalizedDataset.from_dicts("Con huecos", [{"v": 1}, {"v": None}])
    assert len(ENGINE.filter(ds, [FilterClause("v", "is_null")]).rows) == 1
    assert len(ENGINE.filter(ds, [FilterClause("v", "is_not_null")]).rows) == 1


def test_filter_in_and_not_in() -> None:
    ds = _employees()
    inside = ENGINE.filter(ds, [FilterClause("department", "in", ["IT"])])
    outside = ENGINE.filter(ds, [FilterClause("department", "not_in", ["IT"])])
    assert len(inside.rows) == 2
    assert len(outside.rows) == 2
    assert not set(r["name"] for r in inside.rows) & set(r["name"] for r in outside.rows)


def test_filter_does_not_mutate_source_dataset() -> None:
    ds = _employees()
    ENGINE.filter(ds, [FilterClause("department", "eq", "IT")])
    assert len(ds.rows) == 4


# ------------------------------------------------------------------ sort / limit
def test_sort_ascending_and_descending() -> None:
    asc = ENGINE.sort(_employees(), by="salary", ascending=True)
    desc = ENGINE.sort(_employees(), by="salary", ascending=False)
    assert asc.rows[0]["name"] == "Marta"
    assert desc.rows[0]["name"] == "Pedro"


def test_sort_multi_key_respects_independent_direction_per_key() -> None:
    # department ascending (IT before Ventas), salary descending within each department
    ds = ENGINE.sort(_employees(), by=["department", "salary"], ascending=[True, False])
    assert [r["name"] for r in ds.rows] == ["Ana", "Luis", "Pedro", "Marta"]


def test_limit_marks_truncation_and_total_count() -> None:
    ds = ENGINE.limit(_employees(), 2)
    assert len(ds.rows) == 2
    assert ds.is_truncated is True
    assert ds.total_count == 4


def test_limit_no_truncation_when_n_covers_all_rows() -> None:
    ds = ENGINE.limit(_employees(), 10)
    assert ds.is_truncated is False


# ------------------------------------------------------------------ group_by
def test_group_by_computes_aggregates_per_group() -> None:
    ds = ENGINE.group_by(
        _employees(),
        by=["department"],
        aggs=[AggSpec("salary", "mean", alias="salario_medio"), AggSpec("salary", "count")],
    )
    by_dept = {r["department"]: r["salario_medio"] for r in ds.rows}
    assert by_dept["IT"] == 30000.0
    assert by_dept["Ventas"] == 33500.0


def test_group_by_rebuilds_schema_with_agg_columns() -> None:
    ds = ENGINE.group_by(_employees(), by=["department"], aggs=[AggSpec("salary", "sum")])
    names = ds.column_names()
    assert "department" in names
    assert "sum_salary" in names


# ------------------------------------------------------------------ pivot / join / union
def test_pivot_builds_two_way_table() -> None:
    rows = [
        {"dept": "IT", "month": "ene", "amount": 10.0},
        {"dept": "IT", "month": "feb", "amount": 20.0},
        {"dept": "Ventas", "month": "ene", "amount": 5.0},
    ]
    ds = NormalizedDataset.from_dicts("Gasto", rows)
    pivoted = ENGINE.pivot(ds, row_field="dept", col_field="month", value_field="amount", agg="sum")
    by_dept = {r["dept"]: r for r in pivoted.rows}
    assert by_dept["IT"]["ene"] == 10.0
    assert by_dept["IT"]["feb"] == 20.0
    assert by_dept["Ventas"]["feb"] is None


def test_join_left_keeps_unmatched_rows() -> None:
    left = NormalizedDataset.from_dicts("Personas", [{"id": 1, "name": "Ana"}, {"id": 2, "name": "Luis"}])
    right = NormalizedDataset.from_dicts("Salarios", [{"id": 1, "salary": 32000.0}])
    joined = ENGINE.join(left, right, on="id", how="left")
    by_id = {r["id"]: r for r in joined.rows}
    assert by_id[1]["salary"] == 32000.0
    assert by_id[2].get("salary") is None


def test_join_inner_drops_unmatched_rows() -> None:
    left = NormalizedDataset.from_dicts("Personas", [{"id": 1, "name": "Ana"}, {"id": 2, "name": "Luis"}])
    right = NormalizedDataset.from_dicts("Salarios", [{"id": 1, "salary": 32000.0}])
    joined = ENGINE.join(left, right, on="id", how="inner")
    assert len(joined.rows) == 1


def test_union_concatenates_rows_from_all_datasets() -> None:
    a = NormalizedDataset.from_dicts("A", [{"id": 1}])
    b = NormalizedDataset.from_dicts("B", [{"id": 2}])
    merged = ENGINE.union([a, b])
    assert len(merged.rows) == 2


# ------------------------------------------------------------------ derived columns
def test_rank_assigns_1_to_the_best_value_descending() -> None:
    ds = ENGINE.rank(_employees(), by="salary", ascending=False)
    ranks = {r["name"]: r["rank"] for r in ds.rows}
    assert ranks["Pedro"] == 1


def test_add_percentage_sums_to_roughly_100() -> None:
    ds = ENGINE.add_percentage(_employees(), field="salary")
    total_pct = sum(r["salary_pct"] for r in ds.rows)
    assert abs(total_pct - 100.0) < 0.1


def test_percentage_change_uses_first_row_as_base() -> None:
    rows = [{"period": "ene", "value": 100.0}, {"period": "feb", "value": 150.0}]
    ds = NormalizedDataset.from_dicts("Serie", rows)
    out = ENGINE.percentage_change(ds, field="value", group_field="period")
    assert out.rows[1]["value_pct_change"] == 50.0


# ------------------------------------------------------------------ SemanticFieldRegistry
def test_field_registry_resolves_known_synonym() -> None:
    fd = field_registry.resolve("cuánto cobra")
    assert fd is not None
    assert fd.name == "liquido"
    assert fd.permission == "NOMINAS_IMPORTES"


def test_field_registry_resolves_accented_and_unaccented_forms() -> None:
    assert field_registry.resolve("departamento") is field_registry.resolve("area")


def test_field_registry_returns_none_for_unknown_text() -> None:
    assert field_registry.resolve("xyzxyz_no_existe") is None


def test_field_registry_by_domain_filters_correctly() -> None:
    payroll_fields = field_registry.by_domain("payroll")
    assert all(fd.domain == "payroll" for fd in payroll_fields)
    assert any(fd.name == "liquido" for fd in payroll_fields)


# ------------------------------------------------------------------ PeriodEngine
def test_period_engine_hoy() -> None:
    pe = PeriodEngine()
    ref = date(2026, 10, 6)
    period = pe.resolve("hoy", today=ref)
    assert period is not None
    assert period.start == period.end == ref


def test_period_engine_ultimos_n_dias() -> None:
    pe = PeriodEngine()
    ref = date(2026, 10, 6)
    period = pe.resolve("últimos 7 días", today=ref)
    assert period is not None
    assert (period.end - period.start).days == 6
    assert period.end == ref


def test_period_engine_mes_pasado_spans_whole_previous_month() -> None:
    pe = PeriodEngine()
    ref = date(2026, 3, 15)
    period = pe.resolve("mes pasado", today=ref)
    assert period is not None
    assert period.start == date(2026, 2, 1)
    assert period.end == date(2026, 2, 28)


def test_period_engine_quarter_with_explicit_year() -> None:
    pe = PeriodEngine()
    period = pe.resolve("Q2 2025", today=date(2026, 1, 1))
    assert period is not None
    assert period.start == date(2025, 4, 1)
    assert period.end == date(2025, 6, 30)


def test_period_engine_from_to_combines_two_sub_expressions() -> None:
    pe = PeriodEngine()
    ref = date(2026, 12, 31)
    period = pe.resolve("desde enero hasta marzo", today=ref)
    assert period is not None
    assert period.start == date(2026, 1, 1)
    assert period.end == date(2026, 3, 31)


def test_period_engine_unrecognized_expression_returns_none() -> None:
    pe = PeriodEngine()
    assert pe.resolve("esto no es una fecha de verdad", today=date(2026, 1, 1)) is None


def test_period_engine_year_literal() -> None:
    pe = PeriodEngine()
    period = pe.resolve("2024", today=date(2026, 1, 1))
    assert period is not None
    assert period.start == date(2024, 1, 1)
    assert period.end == date(2024, 12, 31)
