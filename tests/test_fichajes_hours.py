"""Horas de turno/nocturnidad/extra por día — pura. Casos confirmados explícitamente por el usuario
(con sus cifras exactas) antes de implementar, para que no se pierdan como regresión futura."""

from __future__ import annotations

from datetime import date, datetime

from mia.modules.rrhh.fichajes.comparison import ShiftExpectation
from mia.modules.rrhh.fichajes.hours import compute_day_hours
from mia.modules.rrhh.fichajes.pairing import ClockSession

DAY = date(2026, 10, 12)


def _dt(hour: int, minute: int = 0, *, next_day: bool = False) -> datetime:
    day = DAY.day + (1 if next_day else 0)
    return datetime(2026, 10, day, hour, minute)


def test_night_shift_crossing_midnight_with_extra_hours_past_the_end() -> None:
    """Turno 18:00-00:00 con 2h nocturnas declaradas; ficha hasta las 02:00: 2h extra, 4h nocturnas
    reales en total (2h normales + 2h extra nocturnas) — ejemplo exacto confirmado por el usuario."""
    shift = ShiftExpectation(DAY, "18:00", "00:00", hours=6.0, declared_night_hours=2.0)
    session = ClockSession(_dt(18), _dt(2, next_day=True))
    result = compute_day_hours(shift, session)
    assert result.horas_programadas == 6.0
    assert result.horas_trabajadas == 8.0
    assert result.horas_nocturnas_normales == 2.0
    assert result.horas_extra == 2.0
    assert result.horas_extra_nocturnas == 2.0
    assert result.horas_extra_diurnas == 0.0
    assert result.balance == 2.0


def test_day_shift_with_zero_declared_night_hours_but_extra_hours_reach_the_night_band() -> None:
    """Turno que termina a las 20:00 (0h nocturnas declaradas: no llega a la franja); ficha hasta
    las 00:00: 4h extra, de las cuales 2h (22:00-00:00) son nocturnas — ejemplo exacto del usuario."""
    shift = ShiftExpectation(DAY, "12:00", "20:00", hours=8.0, declared_night_hours=0.0)
    session = ClockSession(_dt(12), _dt(0, next_day=True))
    result = compute_day_hours(shift, session)
    assert result.horas_programadas == 8.0
    assert result.horas_trabajadas == 12.0
    assert result.horas_nocturnas_normales == 0.0
    assert result.horas_extra == 4.0
    assert result.horas_extra_nocturnas == 2.0
    assert result.horas_extra_diurnas == 2.0
    assert result.balance == 4.0


def test_leaving_before_the_declared_night_window_reports_only_the_night_hours_actually_worked() -> None:
    """Turno 18:00-00:00 con 2h nocturnas declaradas (22:00-00:00); si ficha la salida a las 23:00,
    solo ha trabajado 1h de esa franja — nunca se infla a las 2h declaradas de la definición."""
    shift = ShiftExpectation(DAY, "18:00", "00:00", hours=6.0, declared_night_hours=2.0)
    session = ClockSession(_dt(18), _dt(23))
    result = compute_day_hours(shift, session)
    assert result.horas_nocturnas_normales == 1.0
    assert result.horas_extra == 0.0
    assert result.balance == -1.0
    assert result.balance_pct_turno == round(-1 / 6 * 100, 1)


def test_falta_marcaje_has_zero_worked_hours_and_full_negative_balance() -> None:
    shift = ShiftExpectation(DAY, "08:00", "16:00", hours=8.0, declared_night_hours=0.0)
    result = compute_day_hours(shift, None)
    assert result.horas_trabajadas == 0.0
    assert result.balance == -8.0
    assert result.balance_pct_turno == -100.0
    assert result.balance_pct_fichaje is None


def test_sin_turno_has_no_scheduled_hours_and_is_never_counted_as_extra() -> None:
    """Un día sin turno programado (``shift.start_time`` es ``None``): todo lo fichado es trabajo
    no planificado, nunca se mezcla con "horas extra" de un horario que no existe."""
    shift = ShiftExpectation(DAY, None, None, hours=0.0, declared_night_hours=None)
    session = ClockSession(_dt(9), _dt(17))
    result = compute_day_hours(shift, session)
    assert result.horas_programadas == 0.0
    assert result.horas_extra == 0.0
    assert result.horas_trabajadas == 8.0
    assert result.balance == 8.0
    assert result.balance_pct_turno is None


def test_correct_session_matching_schedule_exactly_has_zero_balance_and_zero_extra() -> None:
    shift = ShiftExpectation(DAY, "08:00", "16:00", hours=8.0, declared_night_hours=0.0)
    session = ClockSession(_dt(8), _dt(16))
    result = compute_day_hours(shift, session)
    assert result.balance == 0.0
    assert result.horas_extra == 0.0
    assert result.horas_nocturnas_normales == 0.0
