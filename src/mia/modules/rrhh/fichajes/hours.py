"""Horas de turno/nocturnidad/extra por día — puro, sin BD, igual que ``pairing.py``/``comparison.py``.

Cuatro magnitudes, nunca mezcladas (requisito explícito del usuario):
  - ``horas_nocturnas_normales``: dentro de lo PROGRAMADO, nunca recalculadas con una franja fija —
    se anclan al final del turno según las horas nocturnas YA DECLARADAS en su definición
    (``ShiftTypeCatalog.hours_night``, ver ``shift_match.py``), porque esa cifra puede corresponder a
    un horario distinto de 22:00-06:00 (turnos que no llegan a esa franja, o que la cruzan de otra
    forma) — nunca se adivina ni se recalcula desde cero.
  - ``horas_extra``: lo fichado más allá de lo programado (antes de la entrada programada o después
    de la salida programada). Puede ser 0.
  - ``horas_extra_nocturnas`` / ``horas_extra_diurnas``: reparto de esas horas extra según si caen en
    la franja fija 22:00-06:00 (``NIGHT_START``/``NIGHT_END``) — esta franja SÍ es fija, pero solo se
    usa para la parte NO programada: decisión explícita del usuario (confirmada), distinta de
    ``horas_nocturnas_normales``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from mia.modules.rrhh.fichajes.comparison import ShiftExpectation
from mia.modules.rrhh.fichajes.pairing import ClockSession

NIGHT_START = time(22, 0)
NIGHT_END = time(6, 0)
"""Franja fija de referencia SOLO para las horas EXTRA (estándar del Estatuto de los Trabajadores,
confirmado explícitamente por el usuario). Nunca se usa para las horas nocturnas normales del
horario: esas vienen siempre de la definición del turno (ver docstring del módulo)."""


@dataclass(frozen=True, slots=True)
class DayHours:
    day: date
    horas_programadas: float
    horas_nocturnas_normales: float
    horas_trabajadas: float
    horas_extra: float
    horas_extra_nocturnas: float
    horas_extra_diurnas: float
    balance: float
    """``horas_trabajadas - horas_programadas``: positivo = trabajó de más, negativo = de menos."""
    balance_pct_turno: float | None
    """``balance / horas_programadas * 100``; ``None`` si no había horas programadas."""
    balance_pct_fichaje: float | None
    """``balance / horas_trabajadas * 100``; ``None`` si no se fichó nada."""


def _parse_hhmm(value: str | None) -> time | None:
    try:
        hh, mm = (value or "").split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def _overlap(a: datetime, b: datetime, c: datetime, d: datetime) -> timedelta:
    lo, hi = max(a, c), min(b, d)
    return hi - lo if hi > lo else timedelta()


def _night_overlap_hours(a: datetime, b: datetime) -> float:
    """Horas de ``[a, b)`` que caen en la franja fija 22:00-06:00, sea el día que sea — se recorre
    día a día del propio intervalo, nunca se asume a priori en qué fecha cae la franja."""
    if b <= a:
        return 0.0
    total = timedelta()
    day = a.date()
    while datetime.combine(day, time.min, tzinfo=a.tzinfo) < b:
        day_start = datetime.combine(day, time.min, tzinfo=a.tzinfo)
        morning_end = datetime.combine(day, NIGHT_END, tzinfo=a.tzinfo)
        evening_start = datetime.combine(day, NIGHT_START, tzinfo=a.tzinfo)
        next_day = day_start + timedelta(days=1)
        total += _overlap(a, b, day_start, morning_end)
        total += _overlap(a, b, evening_start, next_day)
        day += timedelta(days=1)
    return total.total_seconds() / 3600


def compute_day_hours(shift: ShiftExpectation, session: ClockSession | None) -> DayHours:
    """Horas de un día a partir del turno programado y la sesión real ya emparejada
    (``pairing.pair_marks``). ``shift``/``session`` pueden faltar por separado: un día ``sin_turno``
    no tiene horario reconocible más allá de ``day``, y un ``falta_marcaje`` no tiene ``session`` —
    en ambos casos las magnitudes que faltan son 0, nunca se inventan."""
    horas_programadas = shift.hours or 0.0
    horas_trabajadas = session.hours if session else 0.0

    sched_start = _parse_hhmm(shift.start_time)
    sched_end = _parse_hhmm(shift.end_time)
    horas_nocturnas_normales = 0.0
    horas_extra = 0.0
    horas_extra_nocturnas = 0.0

    if session is not None and sched_start is not None and sched_end is not None:
        tz = session.entrada.tzinfo
        entrada_prog = datetime.combine(shift.day, sched_start, tzinfo=tz)
        salida_prog = datetime.combine(shift.day, sched_end, tzinfo=tz)
        if salida_prog <= entrada_prog:
            salida_prog += timedelta(days=1)  # turno que cruza medianoche

        if shift.declared_night_hours:
            night_start_prog = salida_prog - timedelta(hours=shift.declared_night_hours)
            horas_nocturnas_normales = _overlap(
                session.entrada, session.salida, night_start_prog, salida_prog
            ).total_seconds() / 3600

        pre_extra = max(timedelta(), entrada_prog - session.entrada)
        post_extra = max(timedelta(), session.salida - salida_prog)
        horas_extra = (pre_extra + post_extra).total_seconds() / 3600
        if pre_extra:
            horas_extra_nocturnas += _night_overlap_hours(session.entrada, entrada_prog)
        if post_extra:
            horas_extra_nocturnas += _night_overlap_hours(salida_prog, session.salida)

    horas_extra_diurnas = horas_extra - horas_extra_nocturnas
    balance = horas_trabajadas - horas_programadas
    balance_pct_turno = (balance / horas_programadas * 100) if horas_programadas else None
    balance_pct_fichaje = (balance / horas_trabajadas * 100) if horas_trabajadas else None

    return DayHours(
        day=shift.day,
        horas_programadas=round(horas_programadas, 2),
        horas_nocturnas_normales=round(horas_nocturnas_normales, 2),
        horas_trabajadas=round(horas_trabajadas, 2),
        horas_extra=round(horas_extra, 2),
        horas_extra_nocturnas=round(horas_extra_nocturnas, 2),
        horas_extra_diurnas=round(horas_extra_diurnas, 2),
        balance=round(balance, 2),
        balance_pct_turno=round(balance_pct_turno, 1) if balance_pct_turno is not None else None,
        balance_pct_fichaje=round(balance_pct_fichaje, 1) if balance_pct_fichaje is not None else None,
    )
