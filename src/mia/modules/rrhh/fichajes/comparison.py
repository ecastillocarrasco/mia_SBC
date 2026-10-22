"""Comparación turnos (``ShiftDay``) ↔ fichajes (``ClockMark``), por persona — pura, sin BD.

Tres categorías, nunca mezcladas (requisito explícito del usuario):
  - ``falta_marcaje``: turno programado, ningún fichaje ese día.
  - ``sin_turno``: fichaje real sin turno programado ese día (trabajo no planificado).
  - ``desviado`` / ``correcto``: el fichaje SÍ corresponde a un turno programado; se compara la
    hora real contra la programada con un margen de tolerancia (``tolerance_minutes``).
Las marcas sin pareja (``pair_marks``) se devuelven aparte y SIEMPRE se reportan explícitamente
(requisito explícito del usuario) — nunca se mezclan con ninguna de las tres categorías de arriba,
porque no representan ni una sesión completa ni una ausencia: son un dato incompleto en sí mismo.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time

from mia.modules.rrhh.fichajes.pairing import ClockSession, pair_marks

Status = str  # "correcto" | "desviado" | "falta_marcaje" | "sin_turno"


@dataclass(frozen=True, slots=True)
class ShiftExpectation:
    """Lo mínimo de ``ShiftDay`` que necesita la comparación (desacopla de SQLAlchemy)."""

    day: date
    start_time: str | None
    end_time: str | None
    hours: float | None = None
    """Horas totales programadas (``ShiftDay.hours``) — no la usa esta comparación de estado, solo
    se transporta para el cálculo de horas de ``fichajes.hours`` (nunca se duplica aquí)."""
    declared_night_hours: float | None = None
    """Horas nocturnas declaradas en la definición del turno (``fichajes.shift_match``) — mismo
    motivo que ``hours``: solo transporte, sin lógica propia en este módulo."""
    area: str | None = None
    """Área/puesto del turno (``ShiftDay.area``, p. ej. "Piscina") — mismo motivo que ``hours``: solo
    transporte, para mostrar qué turno concreto hizo la persona ese día en el informe."""


@dataclass(frozen=True, slots=True)
class DayComparison:
    day: date
    status: Status
    session: ClockSession | None = None
    entrada_desviacion_min: int | None = None
    """Minutos reales menos programados: positivo = llegó tarde / se fue tarde."""
    salida_desviacion_min: int | None = None


def _parse_hhmm(value: str) -> time | None:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def compare_person(
    shifts: list[ShiftExpectation], marks: list[datetime], *, tolerance_minutes: int = 15
) -> tuple[list[DayComparison], list[datetime]]:
    """(comparación día a día, marcas sin pareja) para UNA persona.

    Simplificación deliberada de esta primera versión: si un día programado tiene más de una
    sesión fichada (turno partido con varias entradas/salidas), se compara contra la PRIMERA
    sesión del día — comparar cada tramo de ``ShiftDay.segments`` por separado queda para una
    iteración futura si resulta necesario, no se adivina aquí.
    """
    sessions, incomplete = pair_marks(marks)
    sessions_by_day: dict[date, list[ClockSession]] = defaultdict(list)
    for session in sessions:
        sessions_by_day[session.entrada.date()].append(session)
    for day_sessions in sessions_by_day.values():
        day_sessions.sort(key=lambda s: s.entrada)
    incomplete_days = {mark.date() for mark in incomplete}

    results: list[DayComparison] = []
    scheduled_days: set[date] = set()
    for shift in shifts:
        scheduled_days.add(shift.day)
        day_sessions = sessions_by_day.get(shift.day)
        if not day_sessions:
            if shift.day in incomplete_days:
                # Hubo un intento de fichaje ese día, pero quedó sin pareja (ver pairing.py): no es
                # "falta_marcaje" (eso ocultaría que sí hubo fichaje) — se deja constancia de que el
                # día está cubierto por una marca incompleta, reportada aparte en `incomplete`.
                continue
            results.append(DayComparison(shift.day, "falta_marcaje"))
            continue
        session = day_sessions[0]
        sched_start = _parse_hhmm(shift.start_time or "")
        sched_end = _parse_hhmm(shift.end_time or "")
        if sched_start is None or sched_end is None:
            # Turno sin horario reconocible (dato incompleto en la propia planificación): se deja
            # constancia de que hubo fichaje, pero no se puede calcular una desviación real.
            results.append(DayComparison(shift.day, "sin_turno", session))
            continue
        # ``session.entrada``/``session.salida`` llegan con zona horaria en PostgreSQL (real) — nunca
        # en SQLite (solo tests), que no la conserva al guardar/leer. ``datetime.combine`` sin
        # ``tzinfo`` crea una fecha "naive": restarla de una "aware" lanza TypeError en producción,
        # aunque los tests con SQLite no lo detecten (ahí ambas acaban siendo "naive" por igual) —
        # bug real encontrado contra datos reales, nunca reproducido por la suite hasta añadir un test
        # con datetimes con zona horaria explícita (ver test_fichajes_comparison.py).
        tz = session.entrada.tzinfo
        entrada_dev = round((session.entrada - datetime.combine(shift.day, sched_start, tzinfo=tz)).total_seconds() / 60)
        salida_dev = round((session.salida - datetime.combine(shift.day, sched_end, tzinfo=tz)).total_seconds() / 60)
        status = "correcto" if abs(entrada_dev) <= tolerance_minutes and abs(salida_dev) <= tolerance_minutes else "desviado"
        results.append(DayComparison(shift.day, status, session, entrada_dev, salida_dev))

    for day, day_sessions in sorted(sessions_by_day.items()):
        if day in scheduled_days:
            continue
        for session in day_sessions:
            results.append(DayComparison(day, "sin_turno", session))

    results.sort(key=lambda r: r.day)
    return results, incomplete
