"""Reglas de transformación heredadas del sistema anterior, ahora explícitas."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from mia.sources import Pseudonymizer
from mia.sources.mappers import hr
from mia.sources.mappers.common import MapContext, boolean, people_field, sp_local_date

CTX = MapContext(tz=ZoneInfo("Europe/Madrid"), pseudonymize=Pseudonymizer("k"), year=2026)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (1, True),
        ("Sí", True),
        ("si", True),
        ("true", True),
        (False, False),
        (0, False),
        (None, False),
    ],
)
def test_active_flag_semantics(value: object, expected: bool) -> None:
    assert boolean(value) is expected


def test_employee_mapping() -> None:
    row = hr.employee(
        {
            "ID": 7,
            "Nombre": "Ángela Pérez",
            "Activo": 1,
            "Departamento": "Pisos",
            "FechaNacimiento": "05/03/1990 00:00",
            "Email": "Angela@SBC.es",
            "DocIdentidad": "abc123",
            "Responsable": {"Title": "Luis", "EMail": "Luis@SBC.es"},
        },
        CTX,
    )[0]
    assert row["name_key"] == "angela perez"
    assert row["active"] is True
    assert row["birth_date"] == date(1990, 3, 5)
    assert row["email"] == "angela@sbc.es"
    assert row["department_key"] == "pisos"
    assert row["manager_email"] == "luis@sbc.es"


def test_pseudonym_is_stable_and_ignores_format() -> None:
    p = Pseudonymizer("clave")
    assert p("12.345.678-z") == p("12345678Z")
    assert p("12345678Z") != Pseudonymizer("otra")("12345678Z")
    assert p("") is None
    assert "12345678" not in (p("12345678Z") or "")


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("09:00-17:00", "Trabajo"),
        ("Recepción | 07:00 - 15:00", "Trabajo"),
        ("VACACIONES", "Vacaciones"),
        ("Descanso", "Descanso"),
        ("LIBRE", "Descanso"),
        ("Baja", "Baja/IT"),
        ("IT", "Baja/IT"),
        ("Asuntos propios", "Asuntos propios"),
        ("Permiso retribuido", "Permiso"),
        ("Festivo", "Festivo"),
        ("", "Sin publicar"),
        ("Formación", "Otro"),
        ("Visita", "Otro"),
    ],
)
def test_shift_kind(value: str, kind: str) -> None:
    assert hr.shift_kind(value) == kind


def test_shift_week_expands_to_seven_days() -> None:
    item = {
        "ID": 3,
        "AnnoTurno": "2026",
        "SemanaTurno": "32",
        "EmpleadoTurno": "Ana",
        "DepartamentoTurno": "Pisos",
        "DNIEmpleado": "pk1",
        "Turno_L": "Recepción | 7:00-15:00",
        "Turno_D": "Descanso",
    }
    days = hr.shift_week(item, CTX)
    assert len(days) == 7
    assert days[0]["day"] == date(2026, 8, 3) and days[0]["weekday"] == "L"
    assert days[0]["area"] == "Recepción"
    assert (days[0]["start_time"], days[0]["end_time"]) == ("07:00", "15:00")
    assert days[6]["kind"] == "Descanso"
    assert days[1]["kind"] == "Sin publicar"


def test_folder_rows_are_skipped() -> None:
    assert hr.shift_week({"ID": 1, "Title": "Carpeta"}, CTX) == []


def test_utc_dates_become_local_dates() -> None:
    # 22:00 UTC del 2 de agosto es ya 3 de agosto en Madrid (verano).
    assert sp_local_date("2026-08-02T22:00:00Z", CTX.tz) == date(2026, 8, 3)


def test_vacation_mapping() -> None:
    row = hr.vacation(
        {
            "ID": 9,
            "Empleado": {"Title": "Ana", "EMail": "ANA@sbc.es"},
            "FechaInicio": "2026-07-31T22:00:00Z",
            "FechaFin": "2026-08-14T22:00:00Z",
            "DiasTotales": "10",
            "Estado": "Aprobada",
        },
        CTX,
    )[0]
    assert (row["start_date"], row["end_date"]) == (date(2026, 8, 1), date(2026, 8, 15))
    assert row["total_days"] == 10.0
    assert row["employee_email"] == "ana@sbc.es"


def test_negative_balance_is_preserved() -> None:
    """VAC-002: un saldo negativo nunca se convierte en cero."""
    row = hr.vacation_balance({"ID": 1, "SaldoActual": "-2,5", "SaldoTotal": 22}, CTX)[0]
    assert row["current_balance"] == -2.5
    assert row["year"] == 2026


def test_department_managers_accept_all_shapes() -> None:
    person = {"Title": "Luis", "EMail": "L@x.es"}
    expected = [{"name": "Luis", "email": "l@x.es"}]
    assert people_field([person]) == expected
    assert people_field({"results": [person]}) == expected
    assert people_field(person) == expected
    assert people_field(None) == []
