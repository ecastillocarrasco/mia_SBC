"""Comparación turnos↔fichajes — pura, sin BD. Cubre las tres categorías pedidas explícitamente
por el usuario (marcaje correcto/desviado, falta de marcaje, trabajo sin turno) y que las marcas
sin pareja se reporten SIEMPRE aparte, nunca mezcladas con ellas."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from mia.modules.rrhh.fichajes.comparison import ShiftExpectation, compare_person


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


def test_matching_session_within_tolerance_is_correcto() -> None:
    shifts = [ShiftExpectation(date(2026, 10, 6), "08:00", "16:00")]
    marks = [_dt(6, 8, 5), _dt(6, 16, 3)]  # 5 min tarde, 3 min tarde: dentro de 15 min
    results, incomplete = compare_person(shifts, marks)
    assert incomplete == []
    assert len(results) == 1
    assert results[0].status == "correcto"
    assert results[0].entrada_desviacion_min == 5
    assert results[0].salida_desviacion_min == 3


def test_session_outside_tolerance_is_desviado() -> None:
    shifts = [ShiftExpectation(date(2026, 10, 6), "08:00", "16:00")]
    marks = [_dt(6, 8, 30), _dt(6, 16, 0)]  # 30 min tarde al entrar: fuera de tolerancia (15)
    results, _ = compare_person(shifts, marks)
    assert results[0].status == "desviado"
    assert results[0].entrada_desviacion_min == 30


def test_scheduled_day_without_any_mark_is_falta_marcaje() -> None:
    shifts = [ShiftExpectation(date(2026, 10, 6), "08:00", "16:00")]
    results, incomplete = compare_person(shifts, [])
    assert incomplete == []
    assert len(results) == 1
    assert results[0].status == "falta_marcaje"
    assert results[0].session is None


def test_session_without_any_scheduled_shift_is_sin_turno() -> None:
    shifts: list[ShiftExpectation] = []
    marks = [_dt(6, 8, 0), _dt(6, 16, 0)]
    results, incomplete = compare_person(shifts, marks)
    assert incomplete == []
    assert len(results) == 1
    assert results[0].status == "sin_turno"
    assert results[0].day == date(2026, 10, 6)


def test_incomplete_mark_is_reported_separately_never_mixed_with_the_three_categories() -> None:
    """Requisito explícito del usuario: una marca sin pareja se marca en el análisis, nunca se
    cuenta como falta de marcaje ni como sesión desviada."""
    shifts = [ShiftExpectation(date(2026, 10, 6), "08:00", "16:00")]
    marks = [_dt(6, 8, 0)]  # entrada sin salida
    results, incomplete = compare_person(shifts, marks)
    assert incomplete == [_dt(6, 8, 0)]
    # El día SÍ tenía un intento de fichaje (entrada), pero como no forma sesión completa no se
    # puede evaluar como correcto/desviado: tampoco debe aparecer como "falta_marcaje" (sería
    # ocultar que SÍ hubo un fichaje, solo que incompleto).
    assert all(r.day != date(2026, 10, 6) for r in results)


def test_split_shift_compares_against_the_first_session_of_the_day() -> None:
    shifts = [ShiftExpectation(date(2026, 10, 7), "12:00", "23:00")]
    marks = [_dt(7, 12, 18), _dt(7, 16, 4), _dt(7, 18, 18), _dt(7, 23, 4)]
    results, incomplete = compare_person(shifts, marks)
    assert incomplete == []
    assert len(results) == 1
    assert results[0].session.entrada == _dt(7, 12, 18)
    assert results[0].session.salida == _dt(7, 16, 4)


def test_multiple_unscheduled_sessions_each_become_their_own_sin_turno() -> None:
    marks = [_dt(6, 8, 0), _dt(6, 12, 0), _dt(7, 8, 0), _dt(7, 12, 0)]
    results, incomplete = compare_person([], marks)
    assert incomplete == []
    assert len(results) == 2
    assert all(r.status == "sin_turno" for r in results)
    assert [r.day for r in results] == [date(2026, 10, 6), date(2026, 10, 7)]


def test_timezone_aware_marks_do_not_crash_comparing_entrada_salida_deviation() -> None:
    """Bug real encontrado contra datos de producción (PostgreSQL, 2026-10-21): ``ClockMark.at``
    llega con zona horaria desde la base de datos real (nunca en SQLite, solo usado en tests, que no
    la conserva al guardar/leer) — comparar esa fecha "aware" contra un ``datetime.combine`` "naive"
    lanzaba ``TypeError: can't subtract offset-naive and offset-aware datetimes``. Esta prueba usa
    zona horaria explícita a propósito para que SÍ la reproduzca, a diferencia del resto del archivo."""
    tz = ZoneInfo("Europe/Madrid")
    shifts = [ShiftExpectation(date(2026, 10, 6), "08:00", "16:00")]
    marks = [datetime(2026, 10, 6, 8, 5, tzinfo=tz), datetime(2026, 10, 6, 16, 3, tzinfo=tz)]
    results, incomplete = compare_person(shifts, marks)
    assert incomplete == []
    assert results[0].status == "correcto"
    assert results[0].entrada_desviacion_min == 5
    assert results[0].salida_desviacion_min == 3
