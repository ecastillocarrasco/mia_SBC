"""Operaciones sobre resultados anteriores (el «álgebra de resultados» del sistema anterior).

* ``operar_resultado``: contar, filtrar, agrupar, ordenar, quedarse con los primeros o
  proyectar columnas del último resultado en tabla, aunque tenga cientos de filas que el
  modelo no ha visto.
* ``cruzar_resultados``: intersección, diferencia o unión de dos poblaciones anteriores
  («de los que están de baja, ¿cuáles también tienen saldo negativo?»).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from mia.conversation import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus
from mia.conversation.tools import HISTORY, LAST_TABLE
from mia.text import normalize_key


def _table(ctx: ToolContext) -> dict[str, Any] | None:
    last = ctx.session_state.get(LAST_TABLE)
    if isinstance(last, dict) and last.get("type") == "table" and last.get("columns"):
        return last
    return None


def _column(columns: list[str], name: str | None) -> int | None:
    if name is None:
        return None
    wanted = normalize_key(name)
    for i, column in enumerate(columns):
        if normalize_key(column) == wanted or wanted in normalize_key(column):
            return i
    return None


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(".", "").replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None


class OperarParams(BaseModel):
    operacion: Literal["contar", "filtrar", "agrupar", "ordenar", "primeros", "columnas"]
    columna: str | None = Field(default=None, description="Columna sobre la que operar")
    valor: str | None = Field(default=None, description="Para filtrar: texto que debe contener la columna")
    descendente: bool = True
    n: int = Field(default=10, ge=1, le=200, description="Para «primeros»")
    columnas: list[str] | None = Field(default=None, description="Para «columnas»: las que se quieren ver")


def operar(p: OperarParams, ctx: ToolContext) -> ToolResult:
    last = _table(ctx)
    if last is None:
        return ToolResult(ToolStatus.NOT_FOUND, "No hay un resultado en tabla anterior sobre el que operar.")
    columns: list[str] = list(last["columns"])
    rows: list[list[Any]] = list(last.get("rows") or [])
    index = _column(columns, p.columna)
    if p.columna and index is None:
        return ToolResult(ToolStatus.INVALID_ARGUMENTS, {"mensaje": "No existe esa columna", "columnas": columns})
    title = str(last.get("title") or "Resultado")
    if p.operacion == "contar":
        return ToolResult(ToolStatus.OK, {"resultado": title, "filas": len(rows)})
    if p.operacion == "agrupar" and index is not None:
        counts = Counter(str(r[index]) for r in rows)
        grouped = [[k, v] for k, v in counts.most_common()]
        return ToolResult(
            ToolStatus.OK,
            {"agrupado_por": columns[index], "grupos": dict(counts.most_common(40))},
            {
                "type": "table",
                "title": f"{title} por {columns[index]}",
                "columns": [columns[index], "Total"],
                "rows": grouped,
            },
        )
    if p.operacion == "filtrar" and index is not None:
        rows = [r for r in rows if normalize_key(p.valor) in normalize_key(r[index])]
    elif p.operacion in {"ordenar", "primeros"} and index is not None:
        rows.sort(
            key=lambda r: (_number(r[index]) is None, _number(r[index]) or 0, str(r[index])),
            reverse=p.descendente,
        )
        rows = [r for r in rows if _number(r[index]) is not None] + [r for r in rows if _number(r[index]) is None]
    if p.operacion == "primeros":
        rows = rows[: p.n]
    if p.operacion == "columnas" and p.columnas:
        keep = [i for c in p.columnas if (i := _column(columns, c)) is not None]
        columns = [columns[i] for i in keep]
        rows = [[r[i] for i in keep] for r in rows]
    presentation = {"type": "table", "title": f"{title} ({p.operacion})", "columns": columns, "rows": rows}
    return ToolResult(ToolStatus.OK, {"filas": len(rows), "columnas": columns, "muestra": rows[:40]}, presentation)


class CruzarParams(BaseModel):
    a: str = Field(description="Etiqueta (o parte) del primer resultado, p. ej. «ausencias»")
    b: str = Field(description="Etiqueta (o parte) del segundo resultado, p. ej. «saldos»")
    operacion: Literal["interseccion", "diferencia", "union"] = "interseccion"


def cruzar(p: CruzarParams, ctx: ToolContext) -> ToolResult:
    history: list[dict[str, Any]] = ctx.session_state.get(HISTORY, [])

    def pick(label: str) -> dict[str, Any] | None:
        return next((h for h in reversed(history) if normalize_key(label) in normalize_key(h.get("etiqueta"))), None)

    first, second = pick(p.a), pick(p.b)
    if first is None or second is None:
        return ToolResult(
            ToolStatus.NOT_FOUND,
            {
                "mensaje": "No encuentro alguno de los resultados",
                "disponibles": [h.get("etiqueta") for h in history],
            },
        )
    a_ids, b_ids = set(first["empleado_ids"]), set(second["empleado_ids"])
    ids = {"interseccion": a_ids & b_ids, "diferencia": a_ids - b_ids, "union": a_ids | b_ids}[p.operacion]
    keep = [i for i, eid in enumerate(first["empleado_ids"] + second["empleado_ids"]) if eid in ids]
    all_ids = first["empleado_ids"] + second["empleado_ids"]
    all_keys = first.get("person_keys", []) + second.get("person_keys", [])
    ordered = list(dict.fromkeys(all_ids[i] for i in keep))
    population = {
        "etiqueta": f"{p.operacion} de «{first['etiqueta']}» y «{second['etiqueta']}»",
        "total": len(ordered),
        "empleado_ids": ordered,
        "person_keys": [k for k in dict.fromkeys(all_keys) if k],
        "emails": [e for e in dict.fromkeys(first.get("emails", []) + second.get("emails", [])) if e],
    }
    return ToolResult(
        ToolStatus.OK,
        {
            "operacion": p.operacion,
            "a": first["etiqueta"],
            "b": second["etiqueta"],
            "personas": len(ordered),
            "nota": "Para ver quiénes son o cruzar con otra consulta, usa sobre_resultado_anterior=true.",
        },
        state_updates={"ultima_poblacion": population},
    )


def register(registry: ToolRegistry) -> None:
    async def _operar(p: OperarParams, ctx: ToolContext) -> ToolResult:
        return operar(p, ctx)

    async def _cruzar(p: CruzarParams, ctx: ToolContext) -> ToolResult:
        return cruzar(p, ctx)

    registry.register(
        Tool(
            "operar_resultado",
            "Cuenta, filtra, agrupa, ordena o proyecta columnas del último "
            "resultado en tabla (aunque tenga muchas filas).",
            OperarParams,
            _operar,
        )
    )
    registry.register(
        Tool(
            "cruzar_resultados",
            "Intersección, diferencia o unión de dos resultados anteriores "
            "con personas («de los de baja, cuáles también…»).",
            CruzarParams,
            _cruzar,
        )
    )
