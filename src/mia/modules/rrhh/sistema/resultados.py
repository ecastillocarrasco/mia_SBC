"""Operaciones sobre resultados anteriores (el «álgebra de resultados» del sistema anterior).

* ``operar_resultado``: contar, filtrar, agrupar, ordenar, quedarse con los primeros o
  proyectar columnas del último resultado en tabla, aunque tenga cientos de filas que el
  modelo no ha visto.
* ``cruzar_resultados``: intersección, diferencia o unión de dos poblaciones anteriores
  («de los que están de baja, ¿cuáles también tienen saldo negativo?»).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from mia.auth import Permission
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


def _distribution_arguments(ctx: ToolContext) -> dict[str, Any] | None:
    if not ctx.user.has(Permission.EMPLEADOS_LEER):
        return None
    match = re.fullmatch(
        r"(?:muestrame|muestra)(?: tambien)? (?:su|la) distribucion por (?P<column>puesto|departamento)",
        normalize_key(ctx.user_message),
    )
    last = _table(ctx)
    if match is None or last is None:
        return None
    column = next((col for col in last["columns"] if normalize_key(col) == match["column"]), None)
    return {"operacion": "agrupar", "columna": column} if column else None


class OperarParams(BaseModel):
    operacion: Literal["contar", "filtrar", "agrupar", "ordenar", "primeros", "columnas"]
    columna: str | None = Field(default=None, description="Columna sobre la que operar")
    valor: str | None = Field(default=None, description="Para filtrar: texto que debe contener la columna")
    descendente: bool = True
    n: int = Field(default=10, ge=1, le=200, description="Para «primeros»")
    columnas: list[str] | None = Field(default=None, description="Para «columnas»: las que se quieren ver")


def _filtered_population(
    ctx: ToolContext, columns: list[str], original_rows: list[list[Any]], rows: list[list[Any]], operation: str
) -> dict[str, Any] | None:
    """Bind selection to known identities; names alone never widen a population."""
    position = next((i for i, col in enumerate(columns) if normalize_key(col) in {"nombre", "persona"}), None)
    population = ctx.session_state.get("ultima_poblacion")
    if position is None or not isinstance(population, dict) or operation not in {"filtrar", "primeros"}:
        return None
    members = population.get("miembros") or []
    by_name = {normalize_key(member.get("nombre")): member for member in members}
    if (
        len(members) != population.get("total")
        or len(by_name) != len(members)
        or "" in by_name
        or {normalize_key(row[position]) for row in original_rows} != set(by_name)
    ):
        raise ValueError(
            "No se puede vincular la tabla a una población completa y sin nombres ambiguos. "
            "Repite la consulta de origen."
        )
    selected_names = {normalize_key(row[position]) for row in rows}
    selected = [member for name, member in by_name.items() if name in selected_names]
    return {
        "etiqueta": f"{population.get('etiqueta', 'Selección')} ({operation})",
        "total": len(selected),
        "miembros": selected,
        "empleado_ids": [member["id"] for member in selected],
        "person_keys": [member["person_key"] for member in selected if member.get("person_key")],
        "emails": [member["email"] for member in selected if member.get("email")],
    }


def operar(p: OperarParams, ctx: ToolContext) -> ToolResult:
    last = _table(ctx)
    if last is None:
        return ToolResult(ToolStatus.NOT_FOUND, "No hay un resultado en tabla anterior sobre el que operar.")
    columns: list[str] = list(last["columns"])
    rows: list[list[Any]] = list(last.get("rows") or [])
    index = _column(columns, p.columna)
    incomplete = p.operacion in {"contar", "agrupar"} and (last.get("__export_meta__") or {}).get("truncated")
    if (p.columna and index is None) or incomplete:
        return ToolResult(
            ToolStatus.INVALID_ARGUMENTS,
            {
                "mensaje": "La tabla anterior está recortada; consulta una fuente completa."
                if incomplete
                else "No existe esa columna",
                "columnas": columns,
            },
        )
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
            verified_answer=(
                f"La distribución por {columns[index]} está en la tabla. Se han agrupado {len(rows)} registros."
            ),
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
    try:
        population = _filtered_population(ctx, columns, list(last.get("rows") or []), rows, p.operacion)
    except ValueError as exc:
        return ToolResult(ToolStatus.INVALID_ARGUMENTS, {"mensaje": str(exc)})
    if p.operacion == "columnas" and p.columnas:
        keep = [i for c in p.columnas if (i := _column(columns, c)) is not None]
        columns = [columns[i] for i in keep]
        rows = [[r[i] for i in keep] for r in rows]
    presentation = {"type": "table", "title": f"{title} ({p.operacion})", "columns": columns, "rows": rows}
    return ToolResult(
        ToolStatus.OK,
        {"filas": len(rows), "columnas": columns, "muestra": rows[:40]},
        presentation,
        state_updates={"ultima_poblacion": population} if population is not None else {},
    )


class CruzarParams(BaseModel):
    a: str = Field(description="referencia_poblacion devuelta por la primera fuente; no inventes etiquetas")
    b: str = Field(description="referencia_poblacion devuelta por la segunda fuente; no inventes etiquetas")
    operacion: Literal["interseccion", "diferencia", "union"] = "interseccion"


def _members(population: dict[str, Any]) -> dict[int, dict[str, Any]] | None:
    ids = population.get("empleado_ids", [])
    if population.get("total") != len(set(ids)) or len(ids) != len(set(ids)):
        return None
    if "miembros" in population:
        members = {item["id"]: item for item in population["miembros"]}
        return members if set(members) == set(ids) else None
    keys, emails = population.get("person_keys", []), population.get("emails", [])
    # Older snapshots contain compact lists. Partial lists cannot be associated
    # with identities safely; require a fresh source instead of guessing.
    if len(keys) not in (0, len(ids)) or len(emails) not in (0, len(ids)):
        return None
    return {
        eid: {"id": eid, "person_key": keys[index] if keys else None, "email": emails[index] if emails else None}
        for index, eid in enumerate(ids)
    }


def _cross_population(first: dict[str, Any], second: dict[str, Any], operation: str) -> dict[str, Any] | None:
    a, b = _members(first), _members(second)
    if a is None or b is None:
        return None
    chosen = {"interseccion": set(a) & set(b), "diferencia": set(a) - set(b), "union": set(a) | set(b)}[operation]
    identities = dict(a)
    for eid, other in b.items():
        original = identities.get(eid, {})
        if any(original.get(key) and other.get(key) and original[key] != other[key] for key in ("person_key", "email")):
            return None
        identities[eid] = {key: other.get(key) or original.get(key) for key in ("id", "person_key", "email")}
    ordered = [eid for eid in dict.fromkeys([*a, *b]) if eid in chosen]
    members = [identities[eid] for eid in ordered]
    return {
        "etiqueta": f"{operation} de «{first['etiqueta']}» y «{second['etiqueta']}»",
        "total": len(ordered),
        "empleado_ids": ordered,
        "person_keys": [item["person_key"] for item in members if item.get("person_key")],
        "emails": [item["email"] for item in members if item.get("email")],
        "miembros": members,
    }


def cruzar(p: CruzarParams, ctx: ToolContext) -> ToolResult:
    history: list[dict[str, Any]] = ctx.session_state.get(HISTORY, [])

    def pick(label: str) -> dict[str, Any] | None:
        wanted = normalize_key(label)
        if not wanted:
            return None
        exact = [h for h in history if wanted == normalize_key(h.get("etiqueta"))]
        matches = exact or [h for h in history if wanted in normalize_key(h.get("etiqueta"))]
        return matches[0] if len(matches) == 1 else None

    first, second = pick(p.a), pick(p.b)
    if first is None or second is None:
        return ToolResult(
            ToolStatus.NOT_FOUND,
            {
                "mensaje": "No encuentro alguno de los resultados",
                "disponibles": [{"referencia_poblacion": h.get("etiqueta"), "total": h.get("total")} for h in history],
            },
        )
    population = _cross_population(first, second, p.operacion)
    if population is None:
        return ToolResult(
            ToolStatus.INVALID_ARGUMENTS,
            "Las selecciones están incompletas o no permiten vincular sus identidades; vuelve a consultar las fuentes.",
        )
    return ToolResult(
        ToolStatus.OK,
        {
            "operacion": p.operacion,
            "a": first["etiqueta"],
            "b": second["etiqueta"],
            "personas": population["total"],
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
            direct_read_arguments=_distribution_arguments,
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
