"""Piezas compartidas por los dominios de RRHH: personas, periodos, frescura y presentación."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.conversation import ToolResult, ToolStatus
from mia.data import Database, Employee, SourceSyncState
from mia.text import normalize_key

STALE_AFTER = timedelta(minutes=30)
MAX_ROWS_FOR_MODEL = 40
"""Filas que ve el modelo; la interfaz recibe la lista completa."""


@dataclass(frozen=True, slots=True)
class Deps:
    db: Database
    stale_after: timedelta = STALE_AFTER

    async def freshness(self, db: AsyncSession, *sources: str) -> dict[str, Any]:
        return await freshness(db, *sources, stale_after=self.stale_after)


# ------------------------------------------------------------------ parámetros comunes
class PersonaParams(BaseModel):
    empleado_id: int | None = Field(
        default=None, description="ID de la persona (del foco o de una búsqueda previa)"
    )
    nombre: str | None = Field(default=None, description="Nombre o parte del nombre, si no hay empleado_id")

    @model_validator(mode="after")
    def _one_of(self) -> PersonaParams:
        if self.empleado_id is None and not (self.nombre or "").strip():
            raise ValueError("Indica empleado_id o nombre")
        return self


class Periodo(BaseModel):
    desde: date | None = Field(default=None, description="Fecha inicial AAAA-MM-DD (por defecto hoy)")
    hasta: date | None = Field(default=None, description="Fecha final AAAA-MM-DD (por defecto igual a desde)")

    def resolve(self, today: date, default_days: int = 0) -> tuple[date, date]:
        start = self.desde or today
        end = self.hasta or (start + timedelta(days=default_days))
        if end < start:
            start, end = end, start
        return start, min(end, start + timedelta(days=366))


# ------------------------------------------------------------------ personas
@dataclass(frozen=True, slots=True)
class PersonMatch:
    status: ToolStatus
    employee: Employee | None = None
    candidates: tuple[Employee, ...] = ()
    suggestions: tuple[str, ...] = ()


def person_summary(e: Employee) -> dict[str, Any]:
    return {
        "empleado_id": e.sp_id,
        "nombre": e.name,
        "departamento": e.department,
        "puesto": e.position,
        "activo": e.active,
    }


def focus_person(e: Employee) -> dict[str, Any]:
    return {"foco_persona": {"empleado_id": e.sp_id, "nombre": e.name, "departamento": e.department}}


async def find_people(db: AsyncSession, query: str, *, include_inactive: bool = True) -> list[Employee]:
    """Coincidencia por palabras: todas las del texto deben aparecer en el nombre (sin tildes)."""
    tokens = [t for t in normalize_key(query).split() if len(t) > 1]
    if not tokens:
        return []
    stmt = select(Employee)
    for token in tokens:
        stmt = stmt.where(or_(Employee.name_key.like(f"{token}%"), Employee.name_key.like(f"% {token}%")))
    if not include_inactive:
        stmt = stmt.where(Employee.active.is_(True))
    return list((await db.scalars(stmt.order_by(Employee.active.desc(), Employee.name))).all())


async def resolve_person(db: AsyncSession, params: PersonaParams) -> PersonMatch:
    if params.empleado_id is not None:
        employee = await db.get(Employee, params.empleado_id)
        return PersonMatch(ToolStatus.OK, employee) if employee else PersonMatch(ToolStatus.NOT_FOUND)
    query = params.nombre or ""
    matches = await find_people(db, query)
    active = [m for m in matches if m.active]
    pool = active or matches
    if len(pool) == 1:
        return PersonMatch(ToolStatus.OK, pool[0])
    if len(pool) > 1:
        exact = [m for m in pool if m.name_key == normalize_key(query)]
        if len(exact) == 1:
            return PersonMatch(ToolStatus.OK, exact[0])
        return PersonMatch(ToolStatus.AMBIGUOUS, candidates=tuple(pool[:10]))
    names = (await db.scalars(select(Employee.name))).all()
    by_key = {normalize_key(n): n for n in names}
    close = difflib.get_close_matches(normalize_key(query), list(by_key), n=3, cutoff=0.75)
    return PersonMatch(ToolStatus.NOT_FOUND, suggestions=tuple(by_key[c] for c in close))


def person_problem(match: PersonMatch, query: str | None) -> ToolResult:
    """Resultado para el modelo cuando la persona no se ha podido fijar."""
    if match.status is ToolStatus.AMBIGUOUS:
        return ToolResult(
            ToolStatus.AMBIGUOUS,
            {
                "mensaje": "Hay varias personas que encajan: pregunta cuál antes de continuar.",
                "candidatos": [person_summary(c) for c in match.candidates],
            },
            table(
                "Personas que encajan",
                ["Nombre", "Departamento", "Puesto", "Activo"],
                [[c.name, c.department, c.position, "Sí" if c.active else "No"] for c in match.candidates],
            ),
        )
    summary: dict[str, Any] = {"mensaje": f"No hay ninguna persona que encaje con «{query}»."}
    if match.suggestions:
        summary["quizas_quiso_decir"] = list(match.suggestions)
    return ToolResult(ToolStatus.NOT_FOUND, summary)


# ------------------------------------------------------------------ frescura de datos
async def freshness(db: AsyncSession, *sources: str, stale_after: timedelta = STALE_AFTER) -> dict[str, Any]:
    """Antigüedad de las fuentes consultadas. ``al_dia`` False solo si superan el umbral."""
    states = {
        s.source: s
        for s in (await db.scalars(select(SourceSyncState).where(SourceSyncState.source.in_(sources)))).all()
    }
    now = datetime.now(UTC)
    oldest: int | None = 0
    never: list[str] = []
    for source in sources:
        state = states.get(source)
        last = state.last_success_at if state else None
        if last is None:
            never.append(source)
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        minutes = int((now - last).total_seconds() // 60)
        oldest = max(oldest or 0, minutes)
    if never:
        return {"al_dia": False, "aviso": "Estas fuentes no se han sincronizado nunca: " + ", ".join(never)}
    if oldest is not None and oldest > stale_after.total_seconds() // 60:
        return {
            "al_dia": False,
            "aviso": f"Última sincronización hace {oldest} minutos: pueden faltar cambios recientes.",
        }
    return {"al_dia": True}


# ------------------------------------------------------------------ presentación
def table(title: str, columns: list[str], rows: list[list[Any]], **extra: Any) -> dict[str, Any]:
    return {"type": "table", "title": title, "columns": columns, "rows": rows, **extra}


def fmt_date(value: date | None) -> str | None:
    return value.strftime("%d/%m/%Y") if value else None


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def merge_periods(days: list[date]) -> list[tuple[date, date]]:
    """Agrupa días consecutivos en periodos: [1,2,3,5] → [(1,3), (5,5)]."""
    periods: list[tuple[date, date]] = []
    for day in sorted(set(days)):
        if periods and day - periods[-1][1] == timedelta(days=1):
            periods[-1] = (periods[-1][0], day)
        else:
            periods.append((day, day))
    return periods


# ------------------------------------------------------------------ departamentos
@dataclass(frozen=True, slots=True)
class DepartmentMatch:
    status: ToolStatus
    name: str | None = None
    key: str | None = None
    options: tuple[str, ...] = ()


async def resolve_department(db: AsyncSession, query: str | None) -> DepartmentMatch:
    """Localiza un departamento por nombre aproximado ("pisos" → "Pisos")."""
    if not (query or "").strip():
        return DepartmentMatch(ToolStatus.OK)
    rows = (await db.execute(select(Employee.department, Employee.department_key).distinct())).all()
    known: dict[str, str] = {key: name for name, key in rows if key and name}
    wanted = normalize_key(query)
    if wanted in known:
        return DepartmentMatch(ToolStatus.OK, known[wanted], wanted)
    partial = [k for k in known if wanted in k or k in wanted]
    if len(partial) == 1:
        return DepartmentMatch(ToolStatus.OK, known[partial[0]], partial[0])
    options = tuple(sorted(known[k] for k in (partial or known)))
    status = ToolStatus.AMBIGUOUS if partial else ToolStatus.NOT_FOUND
    return DepartmentMatch(status, options=options)


def department_problem(match: DepartmentMatch, query: str | None) -> ToolResult:
    verb = (
        "Hay varios departamentos que encajan"
        if match.status is ToolStatus.AMBIGUOUS
        else "No existe ese departamento"
    )
    return ToolResult(match.status, {"mensaje": f"{verb} («{query}»).", "departamentos": list(match.options)})
