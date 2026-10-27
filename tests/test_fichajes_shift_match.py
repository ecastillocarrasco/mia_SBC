"""Cruce ShiftDay ↔ ShiftTypeCatalog (TipoTurnos) por horario exacto dentro del mismo departamento
— nunca por texto libre, nunca adivinado si hay 0 o >1 candidatos."""

from __future__ import annotations

from datetime import date

from mia.data import ShiftDay, ShiftTypeCatalog
from mia.modules.rrhh.fichajes.shift_match import match_shift_type


def _shift_day(start: str, end: str, dept_key: str = "pisos", area: str | None = None) -> ShiftDay:
    return ShiftDay(
        sp_item_id=1,
        day=date(2026, 10, 12),
        person_key="p",
        department_key=dept_key,
        iso_year=2026,
        iso_week=42,
        weekday="L",
        kind="Trabajo",
        start_time=start,
        end_time=end,
        segments=f"{start}-{end}",
        area=area,
    )


def _catalog(
    code: str,
    dept_key: str,
    start1: str,
    end1: str,
    hours_night: float,
    *,
    split=False,
    start2=None,
    end2=None,
    description: str | None = None,
) -> ShiftTypeCatalog:
    return ShiftTypeCatalog(
        sp_id=1,
        code=code,
        department_key=dept_key,
        start1=start1,
        end1=end1,
        start2=start2,
        end2=end2,
        hours_total=0.0,
        hours_night=hours_night,
        split_shift=split,
        description=description,
    )


def test_exact_single_match_returns_its_declared_night_hours() -> None:
    shift = _shift_day("18:00", "00:00")
    catalog = [_catalog("T1", "pisos", "18:00", "00:00", 2.0)]
    match = match_shift_type(shift, catalog)
    assert match.definition is not None
    assert match.definition.hours_night == 2.0
    assert match.ambiguous is False


def test_no_candidate_for_a_schedule_not_in_the_catalog_is_reported_not_guessed() -> None:
    shift = _shift_day("20:00", "00:00")
    catalog = [_catalog("T1", "pisos", "18:00", "00:00", 2.0)]
    match = match_shift_type(shift, catalog)
    assert match.definition is None
    assert match.ambiguous is False


def test_two_catalog_entries_with_the_same_schedule_are_ambiguous() -> None:
    shift = _shift_day("18:00", "00:00")
    catalog = [
        _catalog("T1", "pisos", "18:00", "00:00", 2.0),
        _catalog("T2", "pisos", "18:00", "00:00", 3.0),
    ]
    match = match_shift_type(shift, catalog)
    assert match.definition is None
    assert match.ambiguous is True


def test_same_schedule_shared_by_several_areas_is_disambiguated_by_area() -> None:
    """Caso real confirmado contra TipoTurnos de Pisos (2026-10-21): el mismo horario se repite a
    propósito para varias áreas del departamento («Pisos | 07:00-15:00», «Mozos | 07:00-15:00»,
    «FD | 07:00-15:00»…) — el área de ``ShiftDay`` (ya extraída en la ingesta) debe desambiguar."""
    shift = _shift_day("07:00", "15:00", area="Mozos")
    catalog = [
        _catalog("T1", "pisos", "07:00", "15:00", 0.0, description="Pisos | 07:00 - 15:00"),
        _catalog("T2", "pisos", "07:00", "15:00", 0.0, description="Mozos | 07:00 - 15:00"),
        _catalog("T3", "pisos", "07:00", "15:00", 0.0, description="FD | 07:00 - 15:00"),
    ]
    match = match_shift_type(shift, catalog)
    assert match.definition is not None
    assert match.definition.code == "T2"
    assert match.ambiguous is False


def test_area_matching_is_accent_and_case_insensitive() -> None:
    shift = _shift_day("07:00", "15:00", area="Lavandería")
    catalog = [
        _catalog("T1", "pisos", "07:00", "15:00", 0.0, description="Pisos | 07:00 - 15:00"),
        _catalog("T2", "pisos", "07:00", "15:00", 0.0, description="lavanderia | 07:00 - 15:00"),
    ]
    match = match_shift_type(shift, catalog)
    assert match.definition is not None
    assert match.definition.code == "T2"


def test_duplicate_catalog_rows_that_agree_on_night_hours_are_not_reported_as_ambiguous() -> None:
    """Caso real confirmado (TipoTurnos de Pisos, 2026-10-21): dos filas del maestro para la misma
    área y horario («Pisos | 07:00-15:00» x2), ambas con 0 h nocturnas declaradas — cuál de las dos
    "es la correcta" sigue sin poder saberse, pero para las horas nocturnas da igual: no hace falta
    adivinar para devolver el mismo valor."""
    shift = _shift_day("07:00", "15:00", area="Pisos")
    catalog = [
        _catalog("T1", "pisos", "07:00", "15:00", 0.0, description="Pisos | 07:00 - 15:00"),
        _catalog("T2", "pisos", "07:00", "15:00", 0.0, description="Pisos | 07:00 - 15:00"),
    ]
    match = match_shift_type(shift, catalog)
    assert match.definition is not None
    assert match.definition.hours_night == 0.0
    assert match.ambiguous is False


def test_duplicate_catalog_rows_that_disagree_on_night_hours_stay_ambiguous() -> None:
    shift = _shift_day("07:00", "15:00", area="Pisos")
    catalog = [
        _catalog("T1", "pisos", "07:00", "15:00", 0.0, description="Pisos | 07:00 - 15:00"),
        _catalog("T2", "pisos", "07:00", "15:00", 1.0, description="Pisos | 07:00 - 15:00"),
    ]
    match = match_shift_type(shift, catalog)
    assert match.definition is None
    assert match.ambiguous is True


def test_area_present_on_the_shift_but_absent_from_every_candidate_falls_back_to_schedule_only() -> None:
    """Si ninguna definición declara el área del turno, filtrar por área dejaría 0 candidatos —
    eso NO es "sin definición": se sigue intentando por horario solo, igual que antes del área."""
    shift = _shift_day("07:00", "15:00", area="Mozos")
    catalog = [_catalog("T1", "pisos", "07:00", "15:00", 1.5, description="07:00 - 15:00")]  # sin área
    match = match_shift_type(shift, catalog)
    assert match.definition is not None
    assert match.definition.hours_night == 1.5


def test_same_schedule_in_a_different_department_never_matches() -> None:
    shift = _shift_day("18:00", "00:00", dept_key="pisos")
    catalog = [_catalog("T1", "restaurante", "18:00", "00:00", 2.0)]
    match = match_shift_type(shift, catalog)
    assert match.definition is None
    assert match.ambiguous is False


def test_split_shift_matches_both_segments_in_order() -> None:
    shift = ShiftDay(
        sp_item_id=1,
        day=date(2026, 10, 12),
        person_key="p",
        department_key="pisos",
        iso_year=2026,
        iso_week=42,
        weekday="L",
        kind="Trabajo",
        start_time="10:00",
        end_time="22:00",
        segments="10:00-14:00,18:00-22:00",
    )
    catalog = [_catalog("T1", "pisos", "10:00", "14:00", 1.0, split=True, start2="18:00", end2="22:00")]
    match = match_shift_type(shift, catalog)
    assert match.definition is not None
    assert match.definition.hours_night == 1.0
