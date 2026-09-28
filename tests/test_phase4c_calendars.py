"""Fase 4c: descubrimiento de calendarios, mappers de la planificación v12 y sus herramientas."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mia.auth import UserContext
from mia.conversation import ToolContext, ToolRegistry, ToolStatus
from mia.data import CalendarShift, ShiftDay, ShiftTemplate, ShiftTypeCatalog, WeekComment
from mia.domains import build_registry
from mia.llm import ToolCall
from mia.sources import Pseudonymizer
from mia.sources.definitions import CALENDAR_BASE_YEAR, calendar_source, calendar_title
from mia.sources.discovery import discover_calendar_sources
from mia.sources.mappers import calendars
from mia.sources.mappers.common import MapContext
from mia.sources.sharepoint import SharePointClient, StaticTokenProvider
from mia.sync import SyncRunner
from tests.dbutil import fresh_database
from tests.fakes.sharepoint import FakeSharePoint

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
CTX = MapContext(tz=ZoneInfo("Europe/Madrid"), pseudonymize=Pseudonymizer("k"))


def test_calendar_title_uses_no_suffix_for_the_base_year() -> None:
    assert calendar_title("Pisos", CALENDAR_BASE_YEAR) == "CalendarioPisos"
    assert calendar_title("Pisos", CALENDAR_BASE_YEAR + 1) == f"CalendarioPisos_{CALENDAR_BASE_YEAR + 1}"


def test_shift_kind_matches_legacy_rules() -> None:
    assert calendars.shift_kind("OFF", None) == "off"
    assert calendars.shift_kind("Sin Asignación", None) == "unassigned"
    assert calendars.shift_kind("Mañana", 8.0) == "work"
    assert calendars.shift_kind("Formación", 0) == "special"
    assert calendars.shift_kind(None, None) == "unknown"


async def test_discovery_only_returns_lists_that_actually_exist() -> None:
    fake = FakeSharePoint(page_size=10)
    fake.declare_list("CalendarioPisos")  # 2023, existe pero sin filas todavía
    fake.declare_list("CalendarioPisos_2026")
    client = SharePointClient(site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport())
    found = await discover_calendar_sources(client, departments=("Pisos", "Cocina"), base_year=2023, upto_year=2026)
    await client.aclose()
    assert {s.key for s in found} == {"calendario_pisos_2023", "calendario_pisos_2026"}
    assert all(s.domain == "turnos" for s in found)


async def test_ids_do_not_collide_across_departments_and_years(tmp_path: Path) -> None:
    """La clave primaria compuesta (departamento, año, id) evita choques entre calendarios distintos."""
    db = await fresh_database(tmp_path, "cal.db")
    fake = FakeSharePoint(page_size=10)
    fake.put(
        "CalendarioPisos_2026",
        {
            "ID": 1,
            "DepartamentoTurno": "Pisos",
            "EmpleadoTurno": "Ana Ruiz",
            "StartDate": "2026-08-03T07:00:00Z",
            "EndDate": "2026-08-03T15:00:00Z",
            "DescripcionTurno": "Mañana",
            "HorasTotalesTurno": "8",
        },
    )
    fake.put(
        "CalendarioCocina_2026",
        {
            "ID": 1,
            "DepartamentoTurno": "Cocina",
            "EmpleadoTurno": "Luis Gil",
            "StartDate": "2026-08-03T14:00:00Z",
            "EndDate": "2026-08-03T22:00:00Z",
            "DescripcionTurno": "Tarde",
            "HorasTotalesTurno": "8",
        },
    )
    client = SharePointClient(site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport())
    runner = SyncRunner(db=db, client=client, pseudonymize=Pseudonymizer("k"))
    await runner.run(calendar_source("Pisos", 2026))
    await runner.run(calendar_source("Cocina", 2026))
    await client.aclose()
    async with db.session() as s:
        rows = (await s.execute(_select())).scalars().all()
    await db.dispose()
    assert {(r.department, r.employee_name) for r in rows} == {("Pisos", "Ana Ruiz"), ("Cocina", "Luis Gil")}


def _select() -> Any:
    from sqlalchemy import select  # noqa: PLC0415

    return select(CalendarShift)


def test_split_shift_hours_and_kind() -> None:
    row = calendars.calendar_shift("Recepcion", 2026)(
        {
            "ID": 5,
            "DepartamentoTurno": "Recepcion",
            "EmpleadoTurno": "Eva Marín",
            "StartDate": "2026-08-04T10:00:00Z",
            "EndDate": "2026-08-04T14:00:00Z",
            "DescripcionTurno": "Partido",
            "HorasTotalesTurno": "6,5",
            "HorasNocturnas": "0",
            "TurnoPartido": "1",
        },
        CTX,
    )[0]
    assert row["split_shift"] is True and row["hours_total"] == 6.5 and row["kind"] == "work"


def test_shift_type_catalog_mapper() -> None:
    row = calendars.shift_type(
        {
            "ID": 1,
            "Title": "M",
            "DepartamentoTurno": "Pisos",
            "DescripcionTurno": "Mañana",
            "HorarioInicio": "07:00",
            "HorarioFin": "15:00",
            "HorasTotalesTurno": "8",
        },
        CTX,
    )[0]
    assert row == {
        "sp_id": 1,
        "code": "M",
        "department": "Pisos",
        "department_key": "pisos",
        "description": "Mañana",
        "start1": "07:00",
        "end1": "15:00",
        "start2": None,
        "end2": None,
        "hours_total": 8.0,
        "hours_night": None,
        "split_shift": False,
    }


def test_shift_template_schedule_by_weekday() -> None:
    row = calendars.shift_template(
        {
            "ID": 2,
            "DepartamentoTurno": "Pisos",
            "EmpleadoTurno": "Ana Ruiz",
            "FechaInicioPlantilla": "2026-01-01",
            "FechaFinPlantilla": "2026-12-31",
            "Horario_L": "07:00-15:00",
            "Horario_S": "OFF",
        },
        CTX,
    )[0]
    assert row["schedule"] == {"L": "07:00-15:00", "S": "OFF"}
    assert row["employee_name_key"] == "ana ruiz"


def test_week_comment_mapper() -> None:
    row = calendars.week_comment(
        {
            "ID": 3,
            "DepartamentoTurno": "Pisos",
            "AnnoTurno": "2026",
            "SemanaTurno": "32",
            "ComentariosTurnoPpal": "Refuerzo por ocupación alta",
            "ComentariosTurnoL": "Llegan proveedores",
        },
        CTX,
    )[0]
    assert row["year"] == 2026 and row["week"] == 32
    assert row["day_comments"] == {"L": "Llegan proveedores"}


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[ToolRegistry]:
    db = await fresh_database(tmp_path, "p4c.db")
    async with db.session() as s:
        s.add_all(
            [
                CalendarShift(
                    sp_id=1,
                    department="Pisos",
                    year=2026,
                    department_key="pisos",
                    employee_name="Ana Ruiz",
                    employee_name_key="ana ruiz",
                    day=date(2026, 8, 3),
                    hours_total=8,
                    hours_night=0,
                    kind="work",
                    split_shift=False,
                    description="Mañana",
                ),
                CalendarShift(
                    sp_id=2,
                    department="Pisos",
                    year=2026,
                    department_key="pisos",
                    employee_name="Ana Ruiz",
                    employee_name_key="ana ruiz",
                    day=date(2026, 8, 4),
                    hours_total=0,
                    hours_night=0,
                    kind="off",
                    split_shift=False,
                    description="OFF",
                ),
                CalendarShift(
                    sp_id=3,
                    department="Pisos",
                    year=2026,
                    department_key="pisos",
                    employee_name="Eva Marín",
                    employee_name_key="eva marin",
                    day=date(2026, 8, 3),
                    hours_total=6.5,
                    hours_night=2,
                    kind="work",
                    split_shift=True,
                    description="Partido",
                ),
                ShiftTypeCatalog(
                    sp_id=1,
                    code="M",
                    department="Pisos",
                    department_key="pisos",
                    description="Mañana",
                    start1="07:00",
                    end1="15:00",
                    hours_total=8,
                ),
                ShiftTemplate(
                    sp_id=1,
                    department="Pisos",
                    department_key="pisos",
                    employee_name="Ana Ruiz",
                    employee_name_key="ana ruiz",
                    template_start=date(2026, 1, 1),
                    template_end=date(2026, 12, 31),
                    schedule={"L": "07:00-15:00"},
                ),
                WeekComment(
                    sp_id=1,
                    department="Pisos",
                    department_key="pisos",
                    year=2026,
                    week=32,
                    main_comment="Refuerzo por ocupación alta",
                    day_comments={"L": "Llegan proveedores"},
                ),
                ShiftDay(
                    sp_item_id=1,
                    day=date(2026, 8, 3),
                    person_key="pk-ana",
                    employee_name="Ana Ruiz",
                    department="Pisos",
                    department_key="pisos",
                    iso_year=2026,
                    iso_week=32,
                    weekday="L",
                    kind="Trabajo",
                    raw_value="07:00-15:00",
                ),
            ]
        )
    yield build_registry(db)
    await db.dispose()


async def call(registry: ToolRegistry, name: str, **args: Any) -> Any:
    ctx = ToolContext(user=ADMIN, request_id=None, now=datetime(2026, 8, 5, 10, tzinfo=ZoneInfo("Europe/Madrid")))
    return (await registry.execute(ToolCall("c", name, json.dumps(args)), ctx)).result


async def test_turnos_historico_excludes_off_from_hours(env: ToolRegistry) -> None:
    result = await call(env, "turnos_historico", departamento="Pisos", desde="2026-08-01", hasta="2026-08-31")
    assert result.summary["horas_totales"] == 14.5 and result.summary["total_turnos"] == 3


async def test_turnos_historico_unknown_department(env: ToolRegistry) -> None:
    result = await call(env, "turnos_historico", departamento="Cocinaaa")
    assert result.status is ToolStatus.NOT_FOUND and "Pisos" in result.summary["departamentos"]


async def test_metrics_group_by_person_and_skip_off(env: ToolRegistry) -> None:
    result = await call(env, "metricas_turnos", departamento="Pisos", desde="2026-08-01", hasta="2026-08-31")
    assert result.summary["jornadas_trabajadas"] == 2
    assert result.summary["turnos_partidos"] == 1
    assert result.summary["por_estado"] == {"work": 2, "off": 1}


async def test_catalog_templates_and_week_comment(env: ToolRegistry) -> None:
    catalog = await call(env, "catalogo_tipos_turno", departamento="Pisos")
    assert catalog.summary["tipos"][0]["horario"] == "07:00-15:00"
    templates = await call(env, "plantillas_turno", departamento="Pisos")
    assert "no histórico real" in templates.summary["regla"]
    comment = await call(env, "comentarios_semana_turno", departamento="Pisos", anio=2026, semana=32)
    assert comment.summary["comentario_principal"] == "Refuerzo por ocupación alta"


async def test_publication_audit_flags_the_calendar_only_person(env: ToolRegistry) -> None:
    """Eva tiene turno real en el Calendario ese día, pero no está publicado en Turnos."""
    result = await call(env, "auditoria_publicacion_turnos", departamento="Pisos", fecha="2026-08-03")
    assert result.summary["discrepancias"] == 1
    assert "Eva" in result.summary["detalle"][0]["persona"]


async def test_availability_crosses_calendar_vacations_and_ett(tmp_path: Path) -> None:
    from mia.data import Employee, TtTimesheet, TtWorker, Vacation  # noqa: PLC0415

    db = await fresh_database(tmp_path, "disp.db")
    async with db.session() as s:
        s.add_all(
            [
                Employee(
                    sp_id=1,
                    name="Ana Ruiz",
                    name_key="ana ruiz",
                    active=True,
                    department="Pisos",
                    department_key="pisos",
                    email="ana@x",
                ),
                Employee(
                    sp_id=2,
                    name="Eva Marín",
                    name_key="eva marin",
                    active=True,
                    department="Pisos",
                    department_key="pisos",
                    email="eva@x",
                ),
                Employee(
                    sp_id=3,
                    name="Luz Gil",
                    name_key="luz gil",
                    active=True,
                    department="Pisos",
                    department_key="pisos",
                    email="luz@x",
                ),
                CalendarShift(
                    sp_id=1,
                    department="Pisos",
                    year=2026,
                    department_key="pisos",
                    employee_name="Ana Ruiz",
                    employee_name_key="ana ruiz",
                    day=date(2026, 8, 3),
                    hours_total=8,
                    kind="work",
                    split_shift=False,
                    description="Mañana",
                ),
                CalendarShift(
                    sp_id=2,
                    department="Pisos",
                    year=2026,
                    department_key="pisos",
                    employee_name="Eva Marín",
                    employee_name_key="eva marin",
                    day=date(2026, 8, 3),
                    hours_total=0,
                    kind="special",
                    split_shift=False,
                    description="BAJA IT",
                ),
                Vacation(
                    sp_id=1,
                    employee_email="ana@x",
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 9),
                    status="Aceptada",
                ),
                TtWorker(sp_id=1, name="Leo T", name_key="leo t", visible=True),
                TtTimesheet(
                    sp_id=1,
                    day=date(2026, 8, 3),
                    worker_name="Leo T",
                    department="Pisos",
                    department_key="pisos",
                    hours_total=8,
                ),
            ]
        )
    registry = build_registry(db)
    result = await call(registry, "disponibilidad_dia", departamento="Pisos", fecha="2026-08-03")
    await db.dispose()
    s = result.summary
    assert (s["trabajan"], s["baja_it"], s["sin_planificar"], s["ett_con_boletin"]) == (1, 1, 1, 1)
    assert s["alertas"][0]["persona"] == "Ana Ruiz"  # planificada con vacaciones aceptadas: se señala


async def test_calendar_without_optional_columns_still_syncs(tmp_path: Path) -> None:
    """Fallo real: CalendarioPisos (2023) no tiene UltimaPublicacion ni horas; antes daba HTTP 400."""
    db = await fresh_database(tmp_path, "cal23.db")
    fake = FakeSharePoint(page_size=10)
    fake.put(
        "CalendarioPisos",
        {
            "ID": 7,
            "Title": "t",
            "EmpleadoTurno": "Mercedes Moreno Romero",
            "StartDate": "2023-12-31T08:00:00Z",
            "EndDate": "2023-12-31T16:00:00Z",
            "DescripcionTurno": "FD",
        },
    )
    client = SharePointClient(site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport())
    report = await SyncRunner(db=db, client=client, pseudonymize=Pseudonymizer("k")).run(calendar_source("Pisos", 2023))
    await client.aclose()
    async with db.session() as s:
        row = (await s.execute(_select())).scalars().one()
    await db.dispose()
    select_used = str(fake.requests[-1].url.params.get("$select"))
    assert report.status == "ok" and "UltimaPublicacion" not in select_used
    assert row.hours_total == 8.0 and row.kind == "work"  # horas calculadas del propio evento


def test_shift_type_ignores_malformed_hours() -> None:
    """Fallo real: «0:undefined» en HorarioInicio2 no cabía en la columna."""
    row = calendars.shift_type(
        {
            "ID": 996,
            "Title": "20:00 - 04:00 / 0:undefined - 0:undefined",
            "HorarioInicio": "20:00",
            "HorarioFin": "04:00",
            "HorarioInicio2": "0:undefined",
            "HorarioFin2": "0:undefined",
        },
        CTX,
    )[0]
    assert (row["start1"], row["start2"], row["end2"]) == ("20:00", None, None)


async def test_calendars_do_not_keep_a_raw_copy(tmp_path: Path) -> None:
    """Fallo real: la primera carga de calendarios llenó el disco; su copia original no hace falta."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from mia.data import SourceItem  # noqa: PLC0415

    db = await fresh_database(tmp_path, "raw.db")
    fake = FakeSharePoint(page_size=10)
    fake.put(
        "CalendarioPisos_2026",
        {
            "ID": 1,
            "EmpleadoTurno": "Ana",
            "StartDate": "2026-08-03T07:00:00Z",
            "EndDate": "2026-08-03T15:00:00Z",
            "DescripcionTurno": "M",
        },
    )
    client = SharePointClient(site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport())
    report = await SyncRunner(db=db, client=client, pseudonymize=Pseudonymizer("k")).run(calendar_source("Pisos", 2026))
    await client.aclose()
    async with db.session() as s:
        raw = await s.scalar(select(func.count()).select_from(SourceItem))
        rows = await s.scalar(select(func.count()).select_from(CalendarShift))
    await db.dispose()
    assert report.status == "ok" and (raw, rows) == (0, 1)
