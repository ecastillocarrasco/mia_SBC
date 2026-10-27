"""Emparejamiento de marcas de fichaje — pura, sin BD. Casos tomados de datos reales de Conectia
(semana 41, PISOS/RESTAURANTE): turno simple, turno partido (4 marcas), turno nocturno (cruza
medianoche) y marca suelta que no debe desplazar el resto de la semana."""

from __future__ import annotations

from datetime import datetime

from mia.modules.rrhh.fichajes.pairing import pair_marks


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


def test_simple_pair_entrada_salida() -> None:
    sessions, incomplete = pair_marks([_dt(6, 7, 58), _dt(6, 15, 57)])
    assert incomplete == []
    assert len(sessions) == 1
    assert sessions[0].entrada == _dt(6, 7, 58)
    assert sessions[0].salida == _dt(6, 15, 57)
    assert sessions[0].hours == 7.98


def test_split_shift_four_marks_pairs_into_two_sessions() -> None:
    """Caso real (FERNANDEZ GONZALEZ, JOSE, 07/10): entrada, salida-descanso, vuelta, salida."""
    marks = [_dt(7, 12, 18), _dt(7, 16, 4), _dt(7, 18, 18), _dt(7, 23, 4)]
    sessions, incomplete = pair_marks(marks)
    assert incomplete == []
    assert len(sessions) == 2
    assert (sessions[0].entrada, sessions[0].salida) == (_dt(7, 12, 18), _dt(7, 16, 4))
    assert (sessions[1].entrada, sessions[1].salida) == (_dt(7, 18, 18), _dt(7, 23, 4))


def test_overnight_shift_is_a_single_session_not_split_by_calendar_day() -> None:
    """Entrada a las 20:00 y salida a las 00:01 del día siguiente: una sola sesión de ~4h."""
    sessions, incomplete = pair_marks([_dt(9, 20, 0), _dt(10, 0, 1)])
    assert incomplete == []
    assert len(sessions) == 1
    assert sessions[0].hours == round(4 + 1 / 60, 2)


def test_lone_mark_at_week_boundary_is_incomplete_not_guessed() -> None:
    sessions, incomplete = pair_marks([_dt(5, 7, 51)])
    assert sessions == []
    assert incomplete == [_dt(5, 7, 51)]


def test_missing_mark_breaks_the_chain_instead_of_shifting_the_rest_of_the_week() -> None:
    """Entrada del lunes sin su salida (olvido), seguida de una semana normal: la entrada suelta
    del lunes no debe "robar" la entrada del martes como si fuera su salida."""
    marks = [
        _dt(5, 7, 0),  # lunes: entrada sin salida (olvido)
        _dt(6, 7, 0),
        _dt(6, 15, 0),  # martes: normal
    ]
    sessions, incomplete = pair_marks(marks)
    assert incomplete == [_dt(5, 7, 0)]
    assert len(sessions) == 1
    assert (sessions[0].entrada, sessions[0].salida) == (_dt(6, 7, 0), _dt(6, 15, 0))


def test_gap_larger_than_max_session_breaks_pairing() -> None:
    from mia.modules.rrhh.fichajes.pairing import MAX_SESSION_GAP

    too_far = _dt(5, 7, 0) + MAX_SESSION_GAP + MAX_SESSION_GAP  # muy por encima del límite
    sessions, incomplete = pair_marks([_dt(5, 7, 0), too_far])
    assert sessions == []
    assert sorted(incomplete) == sorted([_dt(5, 7, 0), too_far])


def test_duplicate_exact_timestamp_is_deduplicated() -> None:
    sessions, incomplete = pair_marks([_dt(6, 7, 58), _dt(6, 7, 58), _dt(6, 15, 57)])
    assert incomplete == []
    assert len(sessions) == 1


def test_empty_input() -> None:
    assert pair_marks([]) == ([], [])
