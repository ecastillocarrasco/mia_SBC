"""Periodos reales de ausencia a partir de los turnos publicados.

Regla AUS-001: el periodo de una ausencia es el real, no el recortado por las
fechas consultadas. Si alguien está de baja hoy, su baja empieza el día en que
empezó, aunque la pregunta sea solo por hoy.

Los días sin turno o de descanso entre dos días de la misma ausencia (fines de
semana) no la cortan si son pocos; un día de trabajo sí la cierra.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import ShiftDay
from mia.sources.mappers.hr import ShiftKind

ABSENCE_KINDS = (ShiftKind.BAJA, ShiftKind.VACACIONES, ShiftKind.PERMISO, ShiftKind.ASUNTOS_PROPIOS)
MAX_BRIDGE_DAYS = 3
LOOKBACK = timedelta(days=400)
LOOKAHEAD = timedelta(days=120)


@dataclass(slots=True)
class AbsencePeriod:
    person_key: str
    name: str | None
    department: str | None
    kind: str
    start: date
    end: date
    return_shift: ShiftDay | None = None
    starts_before_data: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def overlaps(self, lo: date, hi: date) -> bool:
        return self.start <= hi and self.end >= lo

    def days_within(self, lo: date, hi: date) -> int:
        return max(0, (min(self.end, hi) - max(self.start, lo)).days + 1)


def build_periods(days: list[ShiftDay], kinds: tuple[str, ...], lower_bound: date) -> list[AbsencePeriod]:
    """Agrupa los días de una persona (ordenados) en periodos de ausencia."""
    periods: list[AbsencePeriod] = []
    current: AbsencePeriod | None = None
    worked_since = False
    for day in days:
        if day.kind in kinds:
            continues = (
                current is not None
                and current.kind == day.kind
                and not worked_since
                and (day.day - current.end).days <= MAX_BRIDGE_DAYS + 1
            )
            if continues and current is not None:
                current.end = day.day
            else:
                current = AbsencePeriod(
                    person_key=str(day.person_key),
                    name=day.employee_name,
                    department=day.department,
                    kind=day.kind,
                    start=day.day,
                    end=day.day,
                    starts_before_data=day.day <= lower_bound,
                )
                periods.append(current)
            worked_since = False
        elif day.kind == ShiftKind.TRABAJO:
            if current is not None and current.return_shift is None and day.day > current.end:
                current.return_shift = day
            worked_since = True
    return periods


async def absence_periods(
    db: AsyncSession,
    *,
    lo: date,
    hi: date,
    kinds: tuple[str, ...] = ABSENCE_KINDS,
    person_keys: list[str] | None = None,
    department_like: str | None = None,
) -> list[AbsencePeriod]:
    """Periodos completos de las personas ausentes en algún día de [lo, hi]."""
    if person_keys is None:
        stmt = (
            select(ShiftDay.person_key)
            .distinct()
            .where(ShiftDay.day.between(lo, hi), ShiftDay.kind.in_(kinds))
        )
        if department_like:
            stmt = stmt.where(ShiftDay.department_key.like(f"%{department_like}%"))
        person_keys = [k for k in (await db.scalars(stmt)).all() if k]
    if not person_keys:
        return []
    start, end = lo - LOOKBACK, hi + LOOKAHEAD
    rows = (
        await db.scalars(
            select(ShiftDay)
            .where(ShiftDay.person_key.in_(person_keys), ShiftDay.day.between(start, end))
            .order_by(ShiftDay.person_key, ShiftDay.day)
        )
    ).all()
    by_person: dict[str, list[ShiftDay]] = defaultdict(list)
    for row in rows:
        by_person[str(row.person_key)].append(row)
    periods = [p for days in by_person.values() for p in build_periods(days, kinds, start)]
    return [p for p in periods if p.overlaps(lo, hi)]
