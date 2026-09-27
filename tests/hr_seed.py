"""Datos de RRHH sintéticos para los tests (ninguna persona real)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from mia.data import Database, Employee, ShiftDay, SourceSyncState, Vacation, VacationBalance

TODAY = date(2026, 8, 5)  # miércoles
WEEKDAYS = "LMXJVSD"


def _emp(sp_id: int, name: str, dept: str, active: bool = True, **kw: object) -> Employee:
    from mia.text import normalize_key  # noqa: PLC0415

    return Employee(
        sp_id=sp_id,
        name=name,
        name_key=normalize_key(name),
        active=active,
        department=dept,
        department_key=normalize_key(dept),
        position=kw.get("position", "Camarera de pisos"),  # type: ignore[arg-type]
        email=kw.get("email"),
        person_key=kw.get("person_key"),  # type: ignore[arg-type]
    )


def _shift(  # noqa: PLR0917
    item: int, person: str, name: str, dept: str, day: date, kind: str, raw: str | None
) -> ShiftDay:
    from mia.text import normalize_key  # noqa: PLC0415

    iso = day.isocalendar()
    return ShiftDay(
        sp_item_id=item,
        day=day,
        person_key=person,
        employee_name=name,
        department=dept,
        department_key=normalize_key(dept),
        iso_year=iso.year,
        iso_week=iso.week,
        weekday=WEEKDAYS[day.weekday()],
        raw_value=raw,
        kind=kind,
        start_time="07:00" if kind == "Trabajo" else None,
        end_time="15:00" if kind == "Trabajo" else None,
    )


async def seed(db: Database, *, fresh: bool = True) -> None:
    ana = "pk-ana"
    rows: list[object] = [
        _emp(1, "Ana Ruiz Sanz", "Pisos", email="ana.ruiz@sbc.test", person_key=ana),
        _emp(2, "Ana Gómez", "Cocina", position="Cocinera", email="ana.gomez@sbc.test", person_key="pk-anag"),
        _emp(3, "Luis Gil", "Cocina", active=False, position="Cocinero"),
        _emp(4, "Eva Sol", "Spa", position="Terapeuta", email="eva@sbc.test", person_key="pk-eva"),
    ]
    # Ana Ruiz: vacaciones de lunes 3 a viernes 7 de agosto, descanso el fin de semana, vuelve el lunes 10.
    week_start = date(2026, 8, 3)
    plan = ["Vacaciones"] * 5 + ["Descanso", "Descanso"] + ["Trabajo"] * 5
    for i, kind in enumerate(plan):
        day = week_start + timedelta(days=i)
        raw = {"Vacaciones": "VACACIONES", "Descanso": "Descanso", "Trabajo": "Recepción | 7:00-15:00"}[kind]
        rows.append(_shift(100 + i // 7, ana, "Ana Ruiz Sanz", "Pisos", day, kind, raw))
    # Eva: baja hoy y mañana; aún sin turnos publicados después.
    for i, kind in enumerate(["Trabajo", "Trabajo", "Baja/IT", "Baja/IT"]):
        day = date(2026, 8, 3) + timedelta(days=i)
        rows.append(_shift(200, "pk-eva", "Eva Sol", "Spa", day, kind, "Baja" if kind == "Baja/IT" else "9:00-17:00"))
    # Ana Gómez trabaja hoy en Cocina.
    rows.append(_shift(300, "pk-anag", "Ana Gómez", "Cocina", TODAY, "Trabajo", "Cocina | 8:00-16:00"))
    rows += [
        Vacation(
            sp_id=1,
            employee_name="Ana Ruiz Sanz",
            employee_email="ana.ruiz@sbc.test",
            department="Pisos",
            department_key="pisos",
            status="Aceptada",
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 7),
            total_days=5,
            request_type="Vacaciones",
        ),
        Vacation(
            sp_id=2,
            employee_name="Ana Ruiz Sanz",
            employee_email="ana.ruiz@sbc.test",
            department="Pisos",
            department_key="pisos",
            status="Pendiente",
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 18),
            total_days=5,
            request_type="Vacaciones",
        ),
        Vacation(
            sp_id=3,
            employee_name="Ana Gómez",
            employee_email="ana.gomez@sbc.test",
            department="Cocina",
            department_key="cocina",
            status="Aceptada",
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 24),
            total_days=3,
            request_type="Asuntos propios",
        ),
        VacationBalance(
            year=2026,
            sp_id=1,
            employee_name="Ana Ruiz Sanz",
            employee_email="ana.ruiz@sbc.test",
            department="Pisos",
            current_balance=-2.5,
            total_balance=22,
        ),
        VacationBalance(
            year=2026,
            sp_id=2,
            employee_name="Ana Gómez",
            employee_email="ana.gomez@sbc.test",
            department="Cocina",
            current_balance=6,
            total_balance=22,
        ),
    ]
    if fresh:
        now = datetime.now(UTC)
        for key in ("empleados", "turnos", "vacaciones", "saldo_vacaciones_2026", "departamentos"):
            rows.append(SourceSyncState(source=key, status="ok", last_success_at=now))
    async with db.session() as s:
        s.add_all(rows)
