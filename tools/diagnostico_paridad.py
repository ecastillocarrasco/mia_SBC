"""Diagnóstico de paridad con el sistema anterior, sobre los datos reales de mIA.

Responde con datos a las diferencias del modo sombra que no se pueden deducir leyendo el código:
  1. ¿Qué tan fresca está cada fuente? (el antiguo lee SharePoint en vivo; mIA, la última sincronización)
  2. Turnos de hoy y de mañana: personas con turno que NO cuentan en mIA y por qué (no hay empleado activo con ese DNI).
  3. Quién figura de baja hoy en Pisos (para cotejarlo con la lista del antiguo).
  4. Vacaciones de hoy desglosadas por tipo y estado.
  5. Saldos negativos con su fecha de actualización.

Uso:  python tools/diagnostico_paridad.py [--departamento Pisos]
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from mia.data import Database, Employee, ShiftDay, SourceSyncState, Vacation, VacationBalance
from mia.modules.rrhh.common import confirmed_vacations
from mia.settings import get_settings
from mia.text import normalize_key


def show(title: str) -> None:
    print(f"\n=== {title} ===")


async def main(department: str) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    now = datetime.now(ZoneInfo(settings.timezone))
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    async with db.session() as s:
        show("1. Frescura de las fuentes (última sincronización correcta)")
        for st in (await s.scalars(select(SourceSyncState).order_by(SourceSyncState.source))).all():
            when = st.last_success_at
            age = f"{int((now - when.astimezone(now.tzinfo)).total_seconds() // 60)} min" if when else "nunca"
            print(f"  {st.source:<32} hace {age:<12} filas {st.item_count}")

        employees = list((await s.scalars(select(Employee))).all())
        by_key = {e.person_key: e for e in employees if e.person_key}
        active_keys = {k for k, e in by_key.items() if e.active}

        for label, day in (("hoy", today), ("mañana", tomorrow)):
            show(f"2. Turnos de trabajo de {label} ({day}) que mIA NO cuenta")
            rows = list(
                (await s.scalars(select(ShiftDay).where(ShiftDay.day == day, ShiftDay.kind == "Trabajo"))).all()
            )
            counted = [r for r in rows if r.person_key in active_keys]
            missing = [r for r in rows if r.person_key not in active_keys]
            print(f"  turnos de trabajo publicados: {len(rows)} · contados por mIA (empleado activo): {len(counted)}")
            print(f"  sin contar: {len(missing)}")
            why = Counter(
                "empleado INACTIVO"
                if (r.person_key in by_key and not by_key[r.person_key].active)
                else ("sin empleado con ese DNI" if r.person_key not in by_key else "otro")
                for r in missing
            )
            print(f"  motivos: {dict(why)}")
            for r in missing[:25]:
                print(f"    - {r.employee_name} · {r.department} · {r.raw_value}")

        show(f"3. De baja hoy en {department} (Baja/IT)")
        key = normalize_key(department)
        sick = list(
            (
                await s.scalars(
                    select(ShiftDay).where(
                        ShiftDay.day == today, ShiftDay.kind == "Baja/IT", ShiftDay.department_key.like(f"%{key}%")
                    )
                )
            ).all()
        )
        print(f"  {len(sick)} filas de baja hoy en el departamento del turno")
        for r in sorted(sick, key=lambda r: r.employee_name or ""):
            e = by_key.get(r.person_key or "")
            state = "activo" if e and e.active else ("INACTIVO" if e else "SIN EMPLEADO")
            current = e.department if e else "—"
            print(f"    - {r.employee_name:<36} {state:<12} dpto. actual del empleado: {current}")

        show("4. Vacaciones de hoy: solicitudes por tipo y estado")
        vacs = list(
            (await s.scalars(select(Vacation).where(Vacation.start_date <= today, Vacation.end_date >= today))).all()
        )
        email_active = {(e.email or "").lower(): e.active for e in employees if e.email}
        table = Counter(
            (
                v.request_type,
                v.status,
                "activo" if email_active.get((v.employee_email or "").lower()) else "no activo/sin ficha",
            )
            for v in vacs
        )
        for (kind, status, state), n in sorted(table.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {kind or '(sin tipo)':<16} {status or '(sin estado)':<16} {state}")
        vacs_vacaciones = [v for v in vacs if normalize_key(v.request_type) == "vacaciones"]
        counted = {
            v.employee_email
            for v in await confirmed_vacations(s, vacs_vacaciones)
            if email_active.get((v.employee_email or "").lower())
        }
        print(f"  → personas de VACACIONES operativas y activas hoy (lo que cuenta mIA): {len(counted)}")

        show("5. Saldos negativos de 2026")
        negatives = list(
            (
                await s.scalars(
                    select(VacationBalance).where(
                        VacationBalance.year == today.year, VacationBalance.current_balance < 0
                    )
                )
            ).all()
        )
        for b in sorted(negatives, key=lambda b: b.current_balance or 0):
            print(f"  {b.current_balance:>6}  {b.employee_name} ({b.department})")
        newest = (
            await s.scalar(select(func.max(VacationBalance.updated_at)))
            if hasattr(VacationBalance, "updated_at")
            else None
        )
        if newest:
            print(f"  (saldo más recientemente actualizado en la fuente: {newest})")
    await db.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--departamento", default="Pisos")
    asyncio.run(main(parser.parse_args().departamento))
