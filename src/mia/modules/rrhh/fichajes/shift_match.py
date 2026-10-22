"""Cruce de un turno real (``ShiftDay``) con su definición (``ShiftTypeCatalog``/«TipoTurnos») para
obtener sus horas nocturnas declaradas — puro, solo recibe los objetos ya cargados, sin I/O propio.

``ShiftDay`` no guarda ningún código que lo enlace con su fila de ``TipoTurnos``: el cruce es por
horario EXACTO dentro del mismo departamento (``department_key`` + tramos de inicio/fin). Verificado
contra datos reales (TipoTurnos de Pisos, 2026-10-21): department_key + horario NO basta por sí solo
— un mismo horario se repite a propósito para varias áreas/puestos distintos dentro del mismo
departamento («Pisos | 07:00-15:00», «Mozos | 07:00-15:00», «FD | 07:00-15:00», «Lavanderia |
07:00-15:00», «Piscina | 07:00-15:00», todas con 0 h nocturnas, confirmado real) — así que el área
(``ShiftDay.area``, ya extraída en la ingesta del texto «Área | horario») se exige TAMBIÉN cuando el
turno la tiene, comparándola contra el mismo prefijo de ``ShiftTypeCatalog.description`` (idéntico
formato «Área | horario» en los datos reales). Si aun así no hay una coincidencia única, se reporta
aparte (``ambiguo`` o ningún candidato) — nunca se adivina cuál es, mismo criterio que
``fichajes.importer``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mia.data import ShiftDay, ShiftTypeCatalog
from mia.text import normalize_key


def _parse_stored_segments(raw: str | None) -> tuple[tuple[str, str], ...]:
    """Tramos ya guardados en ``ShiftDay.segments`` («HH:MM-HH:MM,HH:MM-HH:MM»)."""
    if not raw:
        return ()
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        start, _, end = part.partition("-")
        if start and end:
            out.append((start, end))
    return tuple(out)


def _catalog_segments(catalog: ShiftTypeCatalog) -> tuple[tuple[str, str], ...]:
    segments: list[tuple[str, str]] = []
    if catalog.start1 and catalog.end1:
        segments.append((catalog.start1, catalog.end1))
    if catalog.split_shift and catalog.start2 and catalog.end2:
        segments.append((catalog.start2, catalog.end2))
    return tuple(segments)


def _catalog_area(catalog: ShiftTypeCatalog) -> str | None:
    """Mismo formato «Área | horario» que ``ShiftDay.raw_value`` (ver
    ``mia.ingestion.mappers.hr.shift_week``): el área es el texto antes de la primera barra."""
    description = catalog.description or ""
    area, sep, _ = description.partition("|")
    return area.strip() if sep else None


@dataclass(frozen=True, slots=True)
class ShiftMatch:
    definition: ShiftTypeCatalog | None
    ambiguous: bool
    """``True`` si hay MÁS DE UNA definición con el mismo horario en el departamento — nunca se
    elige una al azar entre ellas."""


def match_shift_type(shift_day: ShiftDay, catalog: Sequence[ShiftTypeCatalog]) -> ShiftMatch:
    """Busca, dentro de ``catalog`` (ya filtrado o no por departamento), la única definición cuyo
    horario — y, si el turno tiene área, también su área — coincide EXACTAMENTE con el de
    ``shift_day``."""
    segments = _parse_stored_segments(shift_day.segments)
    if not segments:
        return ShiftMatch(None, False)
    candidates = [
        c
        for c in catalog
        if c.department_key == shift_day.department_key and _catalog_segments(c) == segments
    ]
    if shift_day.area:
        wanted_area = normalize_key(shift_day.area)
        by_area = [c for c in candidates if normalize_key(_catalog_area(c) or "") == wanted_area]
        # Si filtrar por área deja candidatos, son más precisos que el conjunto solo por horario —
        # pero si ninguno declara esa área (p. ej. el maestro no la registra para este horario), se
        # sigue usando el conjunto por horario: filtrar a cero no es "ningún candidato", es "el área
        # no ayuda aquí", y se reportaría ambiguo/sin definición igual que antes de este ajuste.
        if by_area:
            candidates = by_area
    if len(candidates) == 1:
        return ShiftMatch(candidates[0], False)
    if len(candidates) > 1 and len({c.hours_night for c in candidates}) == 1:
        # Varias filas del maestro siguen empatando en horario (y área, si la había) — confirmado
        # real en TipoTurnos de Pisos (p. ej. dos filas "Pisos | 07:00 - 15:00" duplicadas, ambas con
        # 0 h nocturnas). Cuál de ellas "es la correcta" sigue sin poder determinarse, pero para lo
        # único que usa esta función (``hours_night``) da exactamente igual: no es adivinar el valor,
        # es reconocer que coincide sea cual sea la fila elegida.
        return ShiftMatch(candidates[0], False)
    return ShiftMatch(None, len(candidates) > 1)
