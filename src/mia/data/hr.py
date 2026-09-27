"""Modelo canónico de RRHH, sincronizado desde SharePoint.

Las consultas de mIA leen de aquí (milisegundos), no de SharePoint.
Los identificadores personales (DNI/NIE) nunca se guardan: solo su seudónimo
HMAC (``person_key``), que permite cruzar listas sin exponer el dato.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, LargeBinary, String, Text
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
    nationality: Mapped[str | None] = mapped_column(String(128))
    """Opcional: se rellena cuando la columna exista en EmpleadosCorporativos. Solo usos agregados."""


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
    segments: Mapped[str | None] = mapped_column(String(64))
    """Tramos «HH:MM-HH:MM» separados por comas (varios en un turno partido)."""
    hours: Mapped[float | None] = mapped_column(Float)
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


# ---------------------------------------------------------------------- selección
class Candidate(Base):
    """Candidatura (lista CurriculosVitae)."""

    __tablename__ = "hr_candidates"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(256))
    name_key: Mapped[str] = mapped_column(String(256), index=True)
    email: Mapped[str | None] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(64))
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256), index=True)
    experience: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(64))
    comments: Mapped[str | None] = mapped_column(Text)
    applied_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CvDocument(Base):
    """Fichero de la biblioteca CVDocs (nombre = ID de la candidatura)."""

    __tablename__ = "hr_cv_documents"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    candidate_id: Mapped[int | None] = mapped_column(Integer, index=True)
    file_name: Mapped[str] = mapped_column(String(512))
    file_ref: Mapped[str] = mapped_column(Text)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CvText(Base):
    """Texto extraído de un CV. Vive fuera del ciclo de sincronización para no reextraer a diario."""

    __tablename__ = "hr_cv_texts"

    document_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    candidate_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    """ok · empty · unsupported · too_large · error"""
    text: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CvChunk(Base):
    __tablename__ = "hr_cv_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    """float32 empaquetado; la búsqueda se hace en memoria (≈1.400 CVs)."""


# ---------------------------------------------------------------------- nóminas y documentos
class Payslip(Base):
    """Metadatos de una nómina (biblioteca Nominas). El contenido no se lee ni se guarda."""

    __tablename__ = "hr_payslips"
    __table_args__ = (Index("ix_hr_payslips_person_period", "person_key", "period"),)

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    person_key: Mapped[str | None] = mapped_column(String(64))
    employee_name: Mapped[str | None] = mapped_column(String(256))
    employee_email: Mapped[str | None] = mapped_column(String(256), index=True)
    year: Mapped[int | None] = mapped_column(Integer)
    month: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[str | None] = mapped_column(String(7))
    label: Mapped[str | None] = mapped_column(String(128))
    special: Mapped[bool] = mapped_column(Boolean, default=False)
    read: Mapped[bool | None] = mapped_column(Boolean)
    file_name: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignedDocument(Base):
    """Documento firmado de una persona (biblioteca DocumentosFirmadosV2): solo existencia y tipo."""

    __tablename__ = "hr_signed_documents"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    person_key: Mapped[str | None] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str | None] = mapped_column(String(512))
    doc_year: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------- trabajo temporal
class TtCompany(Base):
    __tablename__ = "hr_tt_companies"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(256))
    cif: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(64))


class TtWorker(Base):
    __tablename__ = "hr_tt_workers"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(256))
    name_key: Mapped[str] = mapped_column(String(256), index=True)
    department: Mapped[str | None] = mapped_column(String(256))
    company: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(64))
    visible: Mapped[bool] = mapped_column(Boolean, default=True)


class TtTimesheet(Base):
    """Boletín de horas de trabajo temporal."""

    __tablename__ = "hr_tt_timesheets"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    day: Mapped[date | None] = mapped_column(Date, index=True)
    worker_name: Mapped[str | None] = mapped_column(String(256))
    worker_id: Mapped[int | None] = mapped_column(Integer)
    company: Mapped[str | None] = mapped_column(String(256))
    company_id: Mapped[int | None] = mapped_column(Integer)
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256), index=True)
    status: Mapped[str | None] = mapped_column(String(64))
    start_time: Mapped[str | None] = mapped_column(String(8))
    end_time: Mapped[str | None] = mapped_column(String(8))
    hours_normal: Mapped[float | None] = mapped_column(Float)
    hours_night: Mapped[float | None] = mapped_column(Float)
    hours_total: Mapped[float | None] = mapped_column(Float)
    diet: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)


# ---------------------------------------------------------------------- fase 4b
class NewHire(Base):
    """Lista AltaEmpleados (aprovisionamiento). No determina si alguien está activo y
    su fecha de creación no es la de incorporación. La contraseña nunca se lee."""

    __tablename__ = "hr_new_hires"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(256))
    name_key: Mapped[str] = mapped_column(String(256), index=True)
    department: Mapped[str | None] = mapped_column(String(256))
    position: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    account: Mapped[str | None] = mapped_column(String(256))
    person_key: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TtRate(Base):
    """Tarifas actuales de una ETT (SettingsTT). Solo para estimaciones; el importe histórico
    está en los boletines."""

    __tablename__ = "hr_tt_rates"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    company: Mapped[str] = mapped_column(String(256))
    company_key: Mapped[str] = mapped_column(String(256), index=True)
    normal_start: Mapped[str | None] = mapped_column(String(8))
    normal_end: Mapped[str | None] = mapped_column(String(8))
    night_start: Mapped[str | None] = mapped_column(String(8))
    night_end: Mapped[str | None] = mapped_column(String(8))
    price_normal: Mapped[float | None] = mapped_column(Float)
    price_night: Mapped[float | None] = mapped_column(Float)
    price_diet: Mapped[float | None] = mapped_column(Float)
    short_contract_surcharge: Mapped[float | None] = mapped_column(Float)


class TtCommunication(Base):
    """Documento de la biblioteca ComunicacionesBoletinesTT (no tiene relación 1:1 con boletines)."""

    __tablename__ = "hr_tt_communications"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str | None] = mapped_column(String(512))
    file_name: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentTypeConfig(Base):
    """Maestros de tipos documentales: TiposDocumentosFirma (RRHH) y TipoDocumento (portal)."""

    __tablename__ = "hr_document_types"

    site: Mapped[str] = mapped_column(String(16), primary_key=True)
    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(256))
    name_key: Mapped[str] = mapped_column(String(256), index=True)
    sign_all: Mapped[bool | None] = mapped_column(Boolean)
    """«FirmarTodas»: toda la plantilla debe firmarlo."""
    requires_authorization: Mapped[bool | None] = mapped_column(Boolean)
