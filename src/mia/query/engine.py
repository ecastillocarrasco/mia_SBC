"""UniversalQueryEngine — filter, sort, group, aggregate en memoria.

Opera sobre NormalizedDataset sin tocar la BD. El LLM nunca ejecuta SQL
arbitrario; solo describe operaciones a través del DSL tipado de este módulo.

Operaciones soportadas:
  filter      — predicados AND sobre campos
  select      — proyección de columnas
  sort        — ordenación por uno o varios campos
  limit       — recorte de filas
  group_by    — agrupación + métricas por grupo
  pivot       — tabla de doble entrada
  join        — combinar dos datasets por clave
  union       — concatenar filas
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from mia.query.dataset import NormalizedDataset, Row, Schema

Comparator = Literal[
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "not_contains",
    "starts_with",
    "in",
    "not_in",
    "is_null",
    "is_not_null",
]

AggFunc = Literal["count", "sum", "mean", "median", "min", "max", "distinct_count", "std"]


# ------------------------------------------------------------------ filter
@dataclass(frozen=True, slots=True)
class FilterClause:
    field: str
    op: Comparator
    value: Any = None


def _match(row: Row, clause: FilterClause) -> bool:
    v = row.get(clause.field)
    ref = clause.value
    op = clause.op
    if op == "is_null":
        return v is None
    if op == "is_not_null":
        return v is not None
    if v is None:
        return False
    if op == "eq":
        return str(v).lower() == str(ref).lower() if isinstance(ref, str) else v == ref
    if op == "neq":
        return str(v).lower() != str(ref).lower() if isinstance(ref, str) else v != ref
    if op == "gt":
        return float(v) > float(ref)
    if op == "gte":
        return float(v) >= float(ref)
    if op == "lt":
        return float(v) < float(ref)
    if op == "lte":
        return float(v) <= float(ref)
    if op == "contains":
        return str(ref).lower() in str(v).lower()
    if op == "not_contains":
        return str(ref).lower() not in str(v).lower()
    if op == "starts_with":
        return str(v).lower().startswith(str(ref).lower())
    if op == "in":
        return v in (ref if isinstance(ref, (list, set, tuple)) else [ref])
    if op == "not_in":
        return v not in (ref if isinstance(ref, (list, set, tuple)) else [ref])
    return True


# ------------------------------------------------------------------ aggregation
def _agg(values: list[float], func: AggFunc) -> float | None:
    if not values:
        return None
    if func == "count":
        return float(len(values))
    if func == "sum":
        return sum(values)
    if func == "mean":
        return sum(values) / len(values)
    if func == "min":
        return min(values)
    if func == "max":
        return max(values)
    if func == "distinct_count":
        return float(len(set(values)))
    if func == "median":
        s = sorted(values)
        n = len(s)
        if n % 2:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2
    if func == "std":
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance**0.5
    return None


@dataclass(frozen=True, slots=True)
class AggSpec:
    field: str
    func: AggFunc
    alias: str | None = None

    @property
    def output_name(self) -> str:
        return self.alias or f"{self.func}_{self.field}"


# ------------------------------------------------------------------ engine
class UniversalQueryEngine:
    """Motor de consulta sobre NormalizedDataset en memoria.

    Todas las operaciones devuelven un nuevo NormalizedDataset; el original
    no se modifica (inmutabilidad funcional).
    """

    # -- filter ----------------------------------------------------------------
    def filter(self, ds: NormalizedDataset, clauses: list[FilterClause]) -> NormalizedDataset:
        rows = [r for r in ds.rows if all(_match(r, c) for c in clauses)]
        return ds.clone_with(rows=rows, title=ds.title)

    # -- select ----------------------------------------------------------------
    def select(self, ds: NormalizedDataset, fields: list[str]) -> NormalizedDataset:
        schema = [s for s in ds.schema if s.name in fields]
        rows = [{f: r.get(f) for f in fields} for r in ds.rows]
        result = ds.clone_with(rows=rows)
        result.schema.clear()
        result.schema.extend(schema)
        return result

    def project(self, ds: NormalizedDataset, fields: list[str]) -> NormalizedDataset:
        """Alias de select."""
        return self.select(ds, fields)

    # -- sort ------------------------------------------------------------------
    def sort(
        self,
        ds: NormalizedDataset,
        by: str | list[str],
        ascending: bool | list[bool] = True,
    ) -> NormalizedDataset:
        keys = [by] if isinstance(by, str) else by
        dirs = [ascending] if isinstance(ascending, bool) else list(ascending)
        while len(dirs) < len(keys):
            dirs.append(True)

        # Sort stably from the least to the most significant key, so each key
        # keeps its own direction (Python's sort is stable: a later pass never
        # disturbs the relative order already settled by an earlier one).
        rows = list(ds.rows)
        for key, asc in reversed(list(zip(keys, dirs, strict=True))):
            rows = sorted(
                rows,
                key=lambda r, k=key: (0 if r.get(k) is None else 1, r.get(k)),
                reverse=not asc,
            )
        return ds.clone_with(rows=rows)

    # -- limit ----------------------------------------------------------------
    def limit(self, ds: NormalizedDataset, n: int, offset: int = 0) -> NormalizedDataset:
        sliced = ds.rows[offset : offset + n]
        result = ds.clone_with(rows=sliced)
        result.is_truncated = len(ds.rows) > offset + n
        result.total_count = len(ds.rows)
        return result

    # -- group_by ------------------------------------------------------------
    def group_by(
        self,
        ds: NormalizedDataset,
        by: list[str],
        aggs: list[AggSpec],
    ) -> NormalizedDataset:
        groups: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
        for row in ds.rows:
            key = tuple(row.get(b) for b in by)
            groups[key].append(row)

        out_rows: list[Row] = []
        for key_vals, group_rows in groups.items():
            out_row: Row = dict(zip(by, key_vals, strict=True))
            for agg in aggs:
                values = [
                    float(r[agg.field])
                    for r in group_rows
                    if r.get(agg.field) is not None and isinstance(r.get(agg.field), (int, float))
                ]
                result = _agg(values, agg.func)
                out_row[agg.output_name] = round(result, 4) if result is not None else None
                out_row[f"_count_{agg.field}"] = len(values)
            out_rows.append(out_row)

        # Rebuild schema
        by_schema = [s for s in ds.schema if s.name in by]
        agg_schema = [
            Schema(
                name=a.output_name,
                label=f"{a.func.capitalize()} {a.field}",
                type="float",
                aggregable=True,
            )
            for a in aggs
        ]
        result_ds = NormalizedDataset(
            title=f"{ds.title} (agrupado por {', '.join(by)})",
            schema=by_schema + agg_schema,
            rows=out_rows,
            source=list(ds.source),
            filters=dict(ds.filters),
            period=dict(ds.period),
        )
        return result_ds

    # -- pivot ----------------------------------------------------------------
    def pivot(
        self,
        ds: NormalizedDataset,
        row_field: str,
        col_field: str,
        value_field: str,
        agg: AggFunc = "sum",
    ) -> NormalizedDataset:
        col_vals = sorted({str(r.get(col_field, "")) for r in ds.rows})
        groups: dict[Any, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in ds.rows:
            rk = row.get(row_field)
            ck = str(row.get(col_field, ""))
            v = row.get(value_field)
            if v is not None and isinstance(v, (int, float)):
                groups[rk][ck].append(float(v))

        out_rows: list[Row] = []
        for rk, col_data in groups.items():
            r: Row = {row_field: rk}
            for ck in col_vals:
                r[ck] = _agg(col_data.get(ck, []), agg)
            out_rows.append(r)

        schema = [Schema(row_field, row_field, "string", aggregable=False)] + [Schema(c, c, "float") for c in col_vals]
        return NormalizedDataset(
            title=f"Pivot {row_field} × {col_field}",
            schema=schema,
            rows=out_rows,
            source=list(ds.source),
        )

    # -- join ----------------------------------------------------------------
    def join(
        self,
        left: NormalizedDataset,
        right: NormalizedDataset,
        on: str,
        how: Literal["inner", "left"] = "left",
    ) -> NormalizedDataset:
        right_by_key: dict[Any, list[Row]] = defaultdict(list)
        for r in right.rows:
            right_by_key[r.get(on)].append(r)

        out_rows: list[Row] = []
        for lrow in left.rows:
            key = lrow.get(on)
            matches = right_by_key.get(key, [])
            if matches:
                for rrow in matches:
                    merged = {**lrow, **{k: v for k, v in rrow.items() if k != on}}
                    out_rows.append(merged)
            elif how == "left":
                out_rows.append(dict(lrow))

        # Merge schemas (avoid duplicates)
        left_names = {s.name for s in left.schema}
        extra_schema = [s for s in right.schema if s.name not in left_names]
        return NormalizedDataset(
            title=f"{left.title} + {right.title}",
            schema=list(left.schema) + extra_schema,
            rows=out_rows,
            source=list(left.source) + list(right.source),
        )

    # -- union ----------------------------------------------------------------
    def union(self, datasets: list[NormalizedDataset]) -> NormalizedDataset:
        if not datasets:
            return NormalizedDataset("Union vacía", [], [])
        all_rows = [r for ds in datasets for r in ds.rows]
        schema = datasets[0].schema
        return NormalizedDataset(
            title=" + ".join(ds.title for ds in datasets),
            schema=schema,
            rows=all_rows,
            source=list({s for ds in datasets for s in ds.source}),
        )

    # -- percentage_change ---------------------------------------------------
    def percentage_change(self, ds: NormalizedDataset, field: str, group_field: str) -> NormalizedDataset:
        """Añade columna {field}_pct_change con la variación porcentual respecto al primer grupo."""
        rows = list(ds.rows)
        if len(rows) < 2:
            return ds
        base = rows[0].get(field)
        if base is None or base == 0:
            return ds
        new_rows = []
        for r in rows:
            v = r.get(field)
            pct = round((float(v) - float(base)) / abs(float(base)) * 100, 2) if v is not None and base else None
            new_rows.append({**r, f"{field}_pct_change": pct})
        extra_schema = [Schema(f"{field}_pct_change", f"Δ% {field}", "float")]
        result = ds.clone_with(rows=new_rows)
        result.schema.extend(extra_schema)
        return result

    # -- rank -----------------------------------------------------------------
    def rank(self, ds: NormalizedDataset, by: str, ascending: bool = False, alias: str = "rank") -> NormalizedDataset:
        sorted_rows = sorted(
            enumerate(ds.rows),
            key=lambda x: (x[1].get(by) is None, x[1].get(by)),
            reverse=not ascending,
        )
        rows_with_rank = []
        for pos, (orig_idx, row) in enumerate(sorted_rows, 1):
            rows_with_rank.append((orig_idx, {**row, alias: pos}))
        rows_with_rank.sort(key=lambda x: x[0])
        out_rows = [r for _, r in rows_with_rank]
        extra_schema = [Schema(alias, "Rank", "int", aggregable=False)]
        result = ds.clone_with(rows=out_rows)
        result.schema.extend(extra_schema)
        return result

    # -- add_percentage -------------------------------------------------------
    def add_percentage(self, ds: NormalizedDataset, field: str, alias: str | None = None) -> NormalizedDataset:
        """Añade columna {alias} con el % que cada fila representa del total."""
        values = [float(r[field]) for r in ds.rows if r.get(field) is not None]
        total = sum(values)
        if total == 0:
            return ds
        out_name = alias or f"{field}_pct"
        out_rows = [
            {**r, out_name: round(float(r[field]) / total * 100, 2) if r.get(field) is not None else None}
            for r in ds.rows
        ]
        extra_schema = [Schema(out_name, f"% {field}", "float", unit="%")]
        result = ds.clone_with(rows=out_rows)
        result.schema.extend(extra_schema)
        return result
