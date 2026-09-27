from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from mia.data import Database, Employee, ShiftDay, SourceItem, SourceSyncState, VacationBalance
from mia.sources import Pseudonymizer, definitions
from mia.sources.sharepoint import SharePointClient, StaticTokenProvider
from mia.sync import SyncMode, SyncRunner
from tests.dbutil import fresh_database
from tests.fakes.sharepoint import FakeSharePoint

EMP = definitions.EMPLEADOS.list_title


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = await fresh_database(tmp_path, "sync.db")
    yield database
    await database.dispose()


@pytest.fixture
def fake() -> FakeSharePoint:
    sp = FakeSharePoint(page_size=2)
    sp.put(
        EMP,
        {"ID": 1, "Nombre": "Ana Ruiz", "Activo": True, "Departamento": "Pisos", "DocIdentidad": "11111111A"},
    )
    sp.put(
        EMP,
        {"ID": 2, "Nombre": "Luis Gil", "Activo": False, "Departamento": "Cocina", "DocIdentidad": "2222B"},
    )
    return sp


@pytest.fixture
async def runner(db: Database, fake: FakeSharePoint) -> AsyncIterator[SyncRunner]:
    client = SharePointClient(
        site_url="https://x/sites/rrhh", tokens=StaticTokenProvider(), transport=fake.transport()
    )
    yield SyncRunner(db=db, client=client, pseudonymize=Pseudonymizer("clave"), full_sync_hour=3)
    await client.aclose()


async def _count(db: Database, model: Any) -> int:
    async with db.session() as s:
        return int(await s.scalar(select(func.count()).select_from(model)) or 0)


async def test_first_run_is_full_and_pseudonymizes(runner: SyncRunner, db: Database) -> None:
    report = await runner.run(definitions.EMPLEADOS)
    assert (report.mode, report.status, report.fetched) == (SyncMode.FULL, "ok", 2)
    async with db.session() as s:
        employees = (await s.scalars(select(Employee).order_by(Employee.sp_id))).all()
        raw = (await s.scalars(select(SourceItem))).all()
        state = await s.get(SourceSyncState, "empleados")
    assert [e.name for e in employees] == ["Ana Ruiz", "Luis Gil"]
    assert employees[0].person_key == Pseudonymizer("clave")("11111111A")
    assert all("11111111A" not in str(r.payload) and "2222B" not in str(r.payload) for r in raw)
    assert state is not None and state.status == "ok" and state.change_token and state.item_count == 2


async def test_incremental_applies_updates_and_deletions(
    runner: SyncRunner, db: Database, fake: FakeSharePoint
) -> None:
    await runner.run(definitions.EMPLEADOS)
    fake.put(EMP, {"ID": 1, "Nombre": "Ana Ruiz Sanz", "Activo": True, "Departamento": "Pisos"})
    fake.put(EMP, {"ID": 3, "Nombre": "Eva Sol", "Activo": True, "Departamento": "Spa"})
    fake.remove(EMP, 2)

    report = await runner.run(definitions.EMPLEADOS)
    assert report.mode is SyncMode.INCREMENTAL
    assert (report.fetched, report.deleted) == (2, 1)
    async with db.session() as s:
        names = (await s.scalars(select(Employee.name).order_by(Employee.sp_id))).all()
        deleted = await s.scalar(select(SourceItem.deleted).where(SourceItem.item_id == 2))
    assert names == ["Ana Ruiz Sanz", "Eva Sol"]
    assert deleted is True
    # Solo se han pedido los elementos cambiados, no la lista entera.
    assert "ID eq 1 or ID eq 3" in str(fake.requests[-1].url.params.get("$filter"))


async def test_nothing_changed_is_cheap(runner: SyncRunner, fake: FakeSharePoint) -> None:
    await runner.run(definitions.EMPLEADOS)
    before = len(fake.requests)
    report = await runner.run(definitions.EMPLEADOS)
    assert report.mode is SyncMode.INCREMENTAL and report.fetched == 0
    assert len(fake.requests) - before == 1  # solo la consulta al registro de cambios


async def test_expired_token_falls_back_to_full(
    runner: SyncRunner, db: Database, fake: FakeSharePoint
) -> None:
    await runner.run(definitions.EMPLEADOS)
    async with db.session() as s:
        token = (await s.get(SourceSyncState, "empleados")).change_token  # type: ignore[union-attr]
    fake.expired_tokens.add(str(token))
    report = await runner.run(definitions.EMPLEADOS)
    assert report.mode is SyncMode.FULL and report.status == "ok"
    assert "token caducado" in report.notes[0]


async def test_full_sync_detects_deletions(runner: SyncRunner, db: Database, fake: FakeSharePoint) -> None:
    await runner.run(definitions.EMPLEADOS)
    fake.lists[EMP].pop(2)  # desaparece sin pasar por el registro de cambios
    report = await runner.run(definitions.EMPLEADOS, SyncMode.FULL)
    assert report.deleted == 1
    assert await _count(db, Employee) == 1


async def test_shift_weeks_are_replaced_not_duplicated(
    runner: SyncRunner, db: Database, fake: FakeSharePoint
) -> None:
    week = {
        "ID": 10,
        "AnnoTurno": "2026",
        "SemanaTurno": "32",
        "DNIEmpleado": "11111111A",
        "Turno_L": "9:00-17:00",
    }
    fake.put("Turnos", week)
    fake.put("Turnos", {"ID": 11, "Title": "Carpeta Pisos"})
    await runner.run(definitions.TURNOS)
    assert await _count(db, ShiftDay) == 7

    fake.put("Turnos", {**week, "Turno_L": "VACACIONES"})
    await runner.run(definitions.TURNOS)
    async with db.session() as s:
        monday = (await s.scalars(select(ShiftDay).where(ShiftDay.weekday == "L"))).one()
    assert await _count(db, ShiftDay) == 7
    assert monday.kind == "Vacaciones"
    assert monday.person_key == Pseudonymizer("clave")("11111111A")


async def test_balance_years_do_not_overwrite_each_other(
    runner: SyncRunner, db: Database, fake: FakeSharePoint
) -> None:
    fake.put("SaldoVacaciones_2025", {"ID": 1, "SaldoActual": 3})
    fake.put("SaldoVacaciones_2026", {"ID": 1, "SaldoActual": -1})
    await runner.run(definitions.saldo_vacaciones(2025))
    await runner.run(definitions.saldo_vacaciones(2026))
    await runner.run(definitions.saldo_vacaciones(2026), SyncMode.FULL)
    async with db.session() as s:
        balances = {b.year: b.current_balance for b in (await s.scalars(select(VacationBalance))).all()}
    assert balances == {2025: 3.0, 2026: -1.0}


async def test_bad_item_does_not_stop_the_sync(runner: SyncRunner, db: Database) -> None:
    def fragile(item: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        if item["ID"] == 2:
            raise ValueError("dato corrupto")
        return definitions.EMPLEADOS.mapper(item, ctx)

    report = await runner.run(replace(definitions.EMPLEADOS, mapper=fragile))
    assert report.status == "ok" and report.item_errors == 1
    assert await _count(db, Employee) == 1


async def test_source_failure_is_recorded(runner: SyncRunner, db: Database, fake: FakeSharePoint) -> None:
    fake.fail_next = [403]
    report = await runner.run(definitions.EMPLEADOS)
    assert report.status == "error"
    async with db.session() as s:
        state = await s.get(SourceSyncState, "empleados")
    assert state is not None and state.status == "error" and "403" in (state.last_error or "")


def test_daily_full_sync_is_scheduled(runner: SyncRunner) -> None:
    state = SourceSyncState(source="x", change_token="t", last_full_at=datetime.now(UTC) - timedelta(days=2))
    assert runner._decide(state, SyncMode.AUTO) is SyncMode.FULL
    state.last_full_at = datetime.now(UTC)
    assert runner._decide(state, SyncMode.AUTO) is SyncMode.INCREMENTAL
    assert runner._decide(None, SyncMode.INCREMENTAL) is SyncMode.FULL


async def test_optional_field_is_requested_only_if_it_exists(
    runner: SyncRunner, db: Database, fake: FakeSharePoint
) -> None:
    await runner.run(definitions.EMPLEADOS)
    assert "Nacionalidad" not in str(fake.requests[-1].url.params.get("$select"))
    fake.put(
        EMP,
        {"ID": 1, "Nombre": "Ana Ruiz", "Activo": True, "Departamento": "Pisos", "Nacionalidad": "Italia"},
    )
    runner._fields.clear()  # un proceso nuevo vuelve a mirar las columnas
    await runner.run(definitions.EMPLEADOS, SyncMode.FULL)
    async with db.session() as s:
        ana = await s.get(Employee, 1)
    assert ana is not None and ana.nationality == "Italia"
