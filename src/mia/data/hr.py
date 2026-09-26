"""Modelo canónico de RRHH, sincronizado desde SharePoint.

Las consultas de mIA leen de aquí (milisegundos), no de SharePoint.
Los identificadores personales (DNI/NIE) nunca se guardan: solo su seudónimo
HMAC (``person_key``), que permite cruzar listas sin exponer el dato.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base


class Employee(Base):
    __tablename__ = "hr_employees"
    __table_args__ = (Index("ix_hr_employees_active_department", "active", "department_key"),)

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    employee_code: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256))
    name_key: Mapped[str] = mapped_column(String(256), index=True)
    active: Mapped[bool] = mapped_column(Boolean)
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256))
    position: Mapped[str | None] = mapped_column(String(256))
    birth_date: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(256), index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    account: Mapped[str | None] = mapped_column(String(256))
    person_key: Mapped[str | None] = mapped_column(String(64), index=True)
    manager_name: Mapped[str | None] = mapped_column(String(256))
    manager_email: Mapped[str | None] = mapped_column(String(256))


class OrgUnit(Base):
    """Sección de un departamento (lista Departamentos: Title = sección, AreaDepartamento = departamento)."""

    __tablename__ = "hr_org_units"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256), index=True)
    section: Mapped[str | None] = mapped_column(String(256))
    section_key: Mapped[str | None] = mapped_column(String(256))
    section_mail: Mapped[str | None] = mapped_column(String(256))
    department_mails: Mapped[str | None] = mapped_column(Text)
    managers: Mapped[list[Any]] = mapped_column(default=list)


class ShiftDay(Base):
    """Un día de turno de una persona (la lista Turnos guarda una fila por persona y semana)."""

    __tablename__ = "hr_shift_days"
    __table_args__ = (
        Index("ix_hr_shift_days_person_day", "person_key", "day"),
        Index("ix_hr_shift_days_department_day", "department_key", "day"),
        Index("ix_hr_shift_days_day_kind", "day", "kind"),
    )

    sp_item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    person_key: Mapped[str | None] = mapped_column(String(64))
    employee_name: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    weekday: Mapped[str] = mapped_column(String(1))
    raw_value: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    area: Mapped[str | None] = mapped_column(String(128))
    start_time: Mapped[str | None] = mapped_column(String(5))
    end_time: Mapped[str | None] = mapped_column(String(5))
    comment: Mapped[str | None] = mapped_column(Text)
    published_by: Mapped[str | None] = mapped_column(String(256))


class Vacation(Base):
    __tablename__ = "hr_vacations"
    __table_args__ = (Index("ix_hr_vacations_dates", "start_date", "end_date"),)

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    employee_lookup_id: Mapped[int | None] = mapped_column(Integer)
    employee_name: Mapped[str | None] = mapped_column(String(256))
    employee_email: Mapped[str | None] = mapped_column(String(256), index=True)
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256), index=True)
    status: Mapped[str | None] = mapped_column(String(64))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    total_days: Mapped[float | None] = mapped_column(Float)
    request_type: Mapped[str | None] = mapped_column(String(128))
    responsible: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VacationBalance(Base):
    """Saldo de vacaciones (una lista por año: SaldoVacaciones_<año>). Puede ser negativo."""

    __tablename__ = "hr_vacation_balances"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    employee_name: Mapped[str | None] = mapped_column(String(256))
    employee_email: Mapped[str | None] = mapped_column(String(256), index=True)
    department: Mapped[str | None] = mapped_column(String(256))
    current_balance: Mapped[float | None] = mapped_column(Float)
    total_balance: Mapped[float | None] = mapped_column(Float)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
