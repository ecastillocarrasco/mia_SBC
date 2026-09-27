"""Reglas de franjas (TUR-001/002) y de periodos de ausencia (AUS-001) sobre datos mínimos."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mia.data import ShiftDay
from mia.domains.turnos.periods import ABSENCE_KINDS, build_periods
from mia.domains.turnos.tools import starts_in, works_at


def shift(
    start: str | None, end: str | None, kind: str = "Trabajo", day: date = date(2026, 8, 3)
) -> ShiftDay:
    return ShiftDay(
        sp_item_id=1,
        day=day,
        person_key="p",
        kind=kind,
        start_time=start,
        end_time=end,
        iso_year=2026,
        iso_week=32,
        weekday="L",
    )


@pytest.mark.parametrize(
    ("start", "band"),
    [
        ("05:00", "mañana"),
        ("07:00", "mañana"),
        ("11:59", "mañana"),
        ("12:00", "tarde"),
        ("16:00", "tarde"),
        ("18:00", "noche"),
        ("22:00", "noche"),
        ("00:00", "noche"),
        ("04:59", "noche"),
    ],
)
def test_band_by_start_time(start: str, band: str) -> None:
    assert starts_in(shift(start, "23:00"), band)


def test_morning_shift_is_not_afternoon_even_if_it_ends_late() -> None:
    assert not starts_in(shift("07:00", "15:00"), "tarde")


def test_presence_by_overlap_crosses_midnight() -> None:
    night = shift("22:00", "06:00")
    assert works_at(night, 2 * 60)
    assert works_at(night, 23 * 60)
    assert not works_at(night, 12 * 60)


def _days(kinds: list[str], start: date = date(2026, 8, 3)) -> list[ShiftDay]:
    return [shift(None, None, kind, start + timedelta(days=i)) for i, kind in enumerate(kinds) if kind]


def test_weekend_rest_does_not_split_a_vacation() -> None:
    days = _days(["Vacaciones"] * 5 + ["Descanso", "Descanso"] + ["Vacaciones"] * 5 + ["Trabajo"])
    periods = build_periods(days, ABSENCE_KINDS, date(2025, 1, 1))
    assert len(periods) == 1
    assert periods[0].days == 12
    assert periods[0].return_shift is not None and periods[0].return_shift.day == date(2026, 8, 15)


def test_a_work_day_closes_the_absence() -> None:
    days = _days(["Baja/IT", "Baja/IT", "Trabajo", "Baja/IT"])
    periods = build_periods(days, ABSENCE_KINDS, date(2025, 1, 1))
    assert [p.days for p in periods] == [2, 1]


def test_long_gap_without_shifts_splits() -> None:
    days = _days(["Baja/IT"] + [""] * 6 + ["Baja/IT"])
    assert len(build_periods(days, ABSENCE_KINDS, date(2025, 1, 1))) == 2
