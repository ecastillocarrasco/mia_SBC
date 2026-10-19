"""Emparejamiento de marcas de fichaje (``ClockMark``) en sesiones entrada/salida.

Pura, sin BD ni I/O — la fidelidad de las marcas en crudo vive en ``ClockMark``; aquí solo se
deriva la sesión y las horas trabajadas, nunca se persiste (ver su docstring: evita una segunda
tabla que se pueda desincronizar). Testeable con listas de ``datetime`` a mano, sin fixtures de BD.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_SESSION_GAP = timedelta(hours=16)
"""Hueco máximo entre una entrada y su salida para considerarlas la misma sesión. Cubre turnos
nocturnos (cruzan medianoche: el hueco real entre marcas sigue siendo corto) y turnos partidos
(varias sesiones cortas el mismo día, con un hueco de descanso entre ellas) — confirmado con datos
reales de Conectia (sección 41, PISOS/RESTAURANTE). Un hueco MAYOR que esto rompe la cadena de
emparejamiento en vez de desplazarla: una sola marca perdida (olvido de fichar) nunca debe
descuadrar el resto de las sesiones de esa persona."""


@dataclass(frozen=True, slots=True)
class ClockSession:
    entrada: datetime
    salida: datetime

    @property
    def hours(self) -> float:
        return round((self.salida - self.entrada).total_seconds() / 3600, 2)


def pair_marks(marks: list[datetime]) -> tuple[list[ClockSession], list[datetime]]:
    """(sesiones completas, marcas sin pareja) a partir de TODAS las marcas de una persona, en
    cualquier orden y sin cortar por día de calendario (un turno nocturno cruza la medianoche).

    Empareja cronológicamente marcas consecutivas si el hueco entre ellas no supera
    ``MAX_SESSION_GAP``; si lo supera, la marca pendiente se reporta como incompleta (nunca se
    adivina su pareja) y el emparejamiento se reinicia desde la siguiente — así una marca perdida
    en mitad de la semana nunca desplaza (ni corrompe) el resto de sesiones posteriores.
    """
    ordered = sorted(set(marks))
    sessions: list[ClockSession] = []
    incomplete: list[datetime] = []
    pending: datetime | None = None
    for mark in ordered:
        if pending is None:
            pending = mark
            continue
        if mark - pending <= MAX_SESSION_GAP:
            sessions.append(ClockSession(pending, mark))
            pending = None
        else:
            incomplete.append(pending)
            pending = mark
    if pending is not None:
        incomplete.append(pending)
    return sessions, incomplete
