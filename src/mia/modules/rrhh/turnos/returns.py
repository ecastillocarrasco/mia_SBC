"""Reincorporaciones: el primer turno de trabajo publicado tras una ausencia (REI-001, mismas fuentes que el antiguo).

  * Baja y permiso → de Turnos, mirando hacia atrás (90 días): una baja que acabó ayer puede volver hoy.
  * Vacaciones y asuntos propios → de la lista de SOLICITUDES de Vacaciones (en estados operativos: aceptada,
    aprobada o pendiente de firma), no de los días marcados en Turnos (que son más y dieron 51 frente a 31).
La fecha de vuelta nunca se supone: es el primer turno de «Trabajo» publicado después de la ausencia.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import Employee, ShiftDay, Vacation
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import confirmed_vacations
from mia.modules.rrhh.turnos.periods import absence_periods
from mia.text import normalize_key

LOOKBACK_DAYS = 90
VACATION_LOOKBACK_DAYS = 21
TURNOS_KINDS = (ShiftKind.BAJA, ShiftKind.PERMISO)
REQUEST_KINDS = {"vacaciones": ShiftKind.VACACIONES, "asuntos propios": ShiftKind.ASUNTOS_PROPIOS}


@dataclass(slots=True)
class ReturnItem:
    person_key: str
    name: str | None
    department: str | None
    kind: str
    start: date
    end: date
    return_day: date | None = None
    return_raw: str | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    """Qué personas y qué ventana: lo compartido por las dos fuentes de reincorporaciones."""

    lo: date
    hi: date
    dept_key: str | None = None
    person_keys: list[str] | None = None
    only_active: bool = True


async def _turnos_returns(db: AsyncSession, kinds: tuple[str, ...], scope: Scope) -> list[ReturnItem]:
    if not kinds:
        return []
    periods = await absence_periods(
        db,
        lo=scope.lo - timedelta(days=LOOKBACK_DAYS),
        hi=scope.hi,
        kinds=kinds,
        department_like=scope.dept_key,
        person_keys=scope.person_keys,
        only_active=scope.only_active,
    )
    floor = scope.lo - timedelta(days=VACATION_LOOKBACK_DAYS)
    return [
        ReturnItem(
            x.person_key,
            x.name,
            x.department,
            x.kind,
            x.start,
            x.end,
            x.return_shift.day if x.return_shift else None,
            x.return_shift.raw_value if x.return_shift else None,
        )
        for x in periods
        if x.end >= floor
    ]


def _blocks(requests: list[Vacation]) -> list[tuple[date, date]]:
    """Solicitudes encadenadas (una empieza al día siguiente de acabar la otra) = una sola ausencia."""
    merged: list[list[date]] = []
    for r in sorted((v for v in requests if v.start_date and v.end_date), key=lambda v: v.start_date or date.min):
        start, end = r.start_date or date.min, r.end_date or date.min
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


async def _request_returns(db: AsyncSession, kinds: tuple[str, ...], scope: Scope) -> list[ReturnItem]:
    wanted = {k for k, v in REQUEST_KINDS.items() if v in kinds}
    if not wanted:
        return []
    floor = scope.lo - timedelta(days=VACATION_LOOKBACK_DAYS)
    candidates = [
        v
        for v in (
            await db.scalars(select(Vacation).where(Vacation.end_date >= floor, Vacation.end_date <= scope.hi))
        ).all()
        if normalize_key(v.request_type) in wanted
    ]
    rows = await confirmed_vacations(db, candidates)
    emails = {(v.employee_email or "").lower() for v in rows if v.employee_email}
    if not emails:
        return []
    stmt = select(Employee).where(func.lower(Employee.email).in_(emails), Employee.person_key.is_not(None))
    if scope.only_active:
        stmt = stmt.where(Employee.active.is_(True))
    if scope.dept_key:
        stmt = stmt.where(Employee.department_key.like(f"%{scope.dept_key}%"))  # departamento ACTUAL del maestro
    if scope.person_keys is not None:
        stmt = stmt.where(Employee.person_key.in_(scope.person_keys))
    by_email = {(e.email or "").lower(): e for e in (await db.scalars(stmt)).all()}
    grouped: dict[tuple[str, str], list[Vacation]] = defaultdict(list)
    for v in rows:
        if (v.employee_email or "").lower() in by_email:
            grouped[((v.employee_email or "").lower(), REQUEST_KINDS[normalize_key(v.request_type)])].append(v)
    candidates = [
        ReturnItem(by_email[mail].person_key or "", by_email[mail].name, by_email[mail].department, kind, a, b)
        for (mail, kind), requests in grouped.items()
        for a, b in _blocks(requests)
        if b >= floor
    ]
    if not candidates:
        return []
    shifts = (
        await db.scalars(
            select(ShiftDay)
            .where(
                ShiftDay.person_key.in_({c.person_key for c in candidates}),
                ShiftDay.kind == ShiftKind.TRABAJO,
                ShiftDay.day > min(c.end for c in candidates),
                ShiftDay.day <= scope.hi,
            )
            .order_by(ShiftDay.day)
        )
    ).all()
    days_by_person: dict[str, list[ShiftDay]] = defaultdict(list)
    for s in shifts:
        if s.person_key:
            days_by_person[s.person_key].append(s)
    for c in candidates:
        first = next((s for s in days_by_person.get(c.person_key, []) if s.day > c.end), None)
        if first:
            c.return_day, c.return_raw = first.day, first.raw_value
    return candidates


async def collect_returns(
    db: AsyncSession,
    *,
    kinds: tuple[str, ...],
    lo: date,
    hi: date,
    dept_key: str | None = None,
    person_keys: list[str] | None = None,
    only_active: bool = True,
) -> tuple[list[ReturnItem], list[ReturnItem]]:
    """(con vuelta publicada dentro de [lo, hi], con la ausencia terminada pero sin turno publicado)."""
    scope = Scope(lo, hi, dept_key, person_keys, only_active)
    items = [
        *await _turnos_returns(db, tuple(k for k in kinds if k in TURNOS_KINDS), scope),
        *await _request_returns(db, kinds, scope),
    ]
    published = [i for i in items if i.return_day is not None and lo <= i.return_day <= hi]
    pending = [i for i in items if i.return_day is None and i.end <= hi]
    published.sort(key=lambda i: (i.return_day or date.max, i.name or ""))
    return published, pending
