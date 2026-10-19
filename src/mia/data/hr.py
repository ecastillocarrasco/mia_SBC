"""Modelo canónico de RRHH, sincronizado desde SharePoint.

Las consultas de mIA leen de aquí (milisegundos), no de SharePoint.
Los identificadores personales (DNI/NIE) nunca se guardan: solo su seudónimo
HMAC (``person_key``), que permite cruzar listas sin exponer el dato.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base

EMBEDDING_DIM = 1536
"""Dimensión de ``text-embedding-3-small`` (OpenAI/Azure OpenAI) — la única usada hoy para indexar."""


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
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Resto de columnas propias de CurriculosVitae (puesto, formación, disponibilidad…), por nombre visible."""
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
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    """Búsqueda por índice HNSW en Postgres (pgvector), no en memoria — ver ``curriculums/search.py``."""


# ---------------------------------------------------------------------- nóminas y documentos
class Payslip(Base):
    """Metadatos de una nómina (biblioteca Nominas).

    El contenido se lee en el momento para importes/análisis (no se guardan cifras sueltas fuera de
    esos cálculos); desde la indexación de contenido sensible (``DataSettings.
    index_sensitive_content``), el TEXTO completo del PDF también se extrae, fragmenta y persiste
    (anonimizado antes de vectorizar, igual que los CVs) en ``hr_document_texts``/``hr_document_chunks``
    para búsqueda semántica — decisión explícita, ver ``Permission.NOMINAS_IMPORTES``."""

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
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Para detectar re-indexación por fichero editado (``DocumentIndexer``, igual que los CVs) —
    SharePoint ``Modified``, nunca ``Created`` (que no cambia si el PDF se reemplaza)."""
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignedDocument(Base):
    """Documento firmado de una persona (biblioteca DocumentosFirmadosV2).

    FIR-001 (metadatos: solo existencia y tipo, nunca contenido ni firma) sigue aplicando a las
    herramientas de resumen. Desde la indexación de contenido sensible (``DataSettings.
    index_sensitive_content``), el TEXTO del documento (incluido "Reconocimiento médico", con el mismo
    anonimizado que el resto — sin excepción) también se extrae, fragmenta y persiste para búsqueda
    semántica — decisión explícita, ver ``Permission.DOCUMENTOS_CONTENIDO``."""

    __tablename__ = "hr_signed_documents"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    person_key: Mapped[str | None] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str | None] = mapped_column(String(512))
    doc_year: Mapped[int | None] = mapped_column(Integer)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Para detectar re-indexación por fichero editado (``DocumentIndexer``, igual que los CVs) —
    SharePoint ``Modified``, nunca ``Created`` (que no cambia si el fichero se reemplaza)."""
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ------------------------------------------------------------- indexación de contenido (genérica)
class HrDocumentText(Base):
    """Texto extraído de un documento sensible (nóminas o documentos firmados), para búsqueda
    semántica — mismo propósito que ``CvText``, generalizado a varios dominios con una clave
    compuesta: ``sp_id`` NO es único entre bibliotecas de SharePoint distintas (``hr_payslips`` y
    ``hr_signed_documents`` pueden coincidir en el mismo número), así que el dominio forma parte de
    la identidad del documento, nunca solo ``document_id``."""

    __tablename__ = "hr_document_texts"

    domain: Mapped[str] = mapped_column(String(32), primary_key=True)
    """``"nominas"`` o ``"documentos_firmados"``."""
    document_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    person_key: Mapped[str | None] = mapped_column(String(64), index=True)
    source_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    """ok · empty · unsupported · too_large · error"""
    text: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HrDocumentChunk(Base):
    """Fragmento con embedding de un documento sensible — mismo propósito que ``CvChunk``,
    generalizado por dominio (ver ``HrDocumentText``)."""

    __tablename__ = "hr_document_chunks"
    __table_args__ = (
        Index("ix_hr_document_chunks_domain_document", "domain", "document_id"),
        Index("ix_hr_document_chunks_domain_person", "domain", "person_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[int] = mapped_column(Integer)
    person_key: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    """Búsqueda por índice HNSW en Postgres (pgvector), igual que ``CvChunk`` — ver ``document_search.py``."""


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


# ---------------------------------------------------------------------- calendarios de turnos (planificación v12)
class CalendarShift(Base):
    """Un evento de turno del Calendario<Departamento>_AAAA (fuente histórica real).

    Identifica a la persona por nombre (estas listas no tienen DNI), a diferencia de
    Turnos: ``turnos_historico`` resuelve el nombre contra Employee en el momento de
    la consulta, igual que ``buscar_empleado``.
    """

    __tablename__ = "hr_calendar_shifts"
    __table_args__ = (
        Index("ix_hr_calendar_shifts_dept_day", "department_key", "day"),
        Index("ix_hr_calendar_shifts_person_day", "employee_name_key", "day"),
    )

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    department: Mapped[str] = mapped_column(String(256), primary_key=True, autoincrement=False)
    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    """department + year identifican la lista de origen: sus IDs solo son únicos dentro de ella."""
    department_key: Mapped[str] = mapped_column(String(256), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(256))
    employee_name_key: Mapped[str | None] = mapped_column(String(256), index=True)
    day: Mapped[date] = mapped_column(Date)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(String(256))
    comment: Mapped[str | None] = mapped_column(Text)
    hours_total: Mapped[float | None] = mapped_column(Float)
    hours_night: Mapped[float | None] = mapped_column(Float)
    split_shift: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(16), default="unknown")
    """work · off · unassigned · special · unknown (mismo criterio que las métricas del sistema anterior)."""
    week: Mapped[int | None] = mapped_column(Integer)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_count: Mapped[int | None] = mapped_column(Integer)
    report_sent: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShiftTypeCatalog(Base):
    """Maestro TipoTurnos: la definición canónica de cada turno por departamento."""

    __tablename__ = "hr_shift_type_catalog"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(64))
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(String(256))
    start1: Mapped[str | None] = mapped_column(String(8))
    end1: Mapped[str | None] = mapped_column(String(8))
    start2: Mapped[str | None] = mapped_column(String(8))
    end2: Mapped[str | None] = mapped_column(String(8))
    hours_total: Mapped[float | None] = mapped_column(Float)
    hours_night: Mapped[float | None] = mapped_column(Float)
    split_shift: Mapped[bool] = mapped_column(Boolean, default=False)


class ShiftTemplate(Base):
    """TurnosPlantillas: reglas/patrones de generación de turnos, NO histórico real."""

    __tablename__ = "hr_shift_templates"

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(256))
    employee_name_key: Mapped[str | None] = mapped_column(String(256), index=True)
    template_start: Mapped[date | None] = mapped_column(Date)
    template_end: Mapped[date | None] = mapped_column(Date)
    anchor_date: Mapped[date | None] = mapped_column(Date)
    schedule: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Horario por día de la semana: {"L": "09:00-17:00", ...}."""
    comment: Mapped[str | None] = mapped_column(Text)
    split_count: Mapped[int | None] = mapped_column(Integer)
    night_hours: Mapped[float | None] = mapped_column(Float)
    week: Mapped[int | None] = mapped_column(Integer)


class ClockMark(Base):
    """Un fichaje (marca de entrada o salida) de control de presencia.

    Fuente actual: exportación Excel de Conectia (A3 Wolters Kluwer), vía importación manual
    — ``source="excel_conectia"`` lo distingue desde ya de una futura API real (``TimeClockConnector``,
    ``mia.connectors.a3``) sin romper nada cuando esa API exista. El emparejamiento entrada/salida y el
    cálculo de horas NO se guardan aquí: viven en ``mia.modules.rrhh.fichajes.pairing`` como función
    pura sobre la secuencia de marcas de una persona, igual que ``parse_payslip`` nunca mezcla lectura
    y cálculo — evita una segunda tabla derivada que se pueda desincronizar de esta.
    """

    __tablename__ = "hr_clock_marks"
    __table_args__ = (Index("ix_hr_clock_marks_person_at", "person_key", "at"),)

    person_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    origin: Mapped[str | None] = mapped_column(String(64))
    """"Origen del marcaje" (Conectia): «Normal» salvo corrección manual futura."""
    device_type: Mapped[str | None] = mapped_column(String(32))
    """"Tipo marcaje": «Reloj», «App», «App offline»."""
    terminal_name: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32))
    """«excel_conectia» hoy; reservado para distinguir una futura fuente (API real) sin migrar datos."""
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WeekComment(Base):
    """ComentariosTurnosSemanas: contexto de departamento/semana. Nunca se atribuye a una persona."""

    __tablename__ = "hr_week_comments"
    __table_args__ = (Index("ix_hr_week_comments_dept_week", "department_key", "year", "week"),)

    sp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    department: Mapped[str | None] = mapped_column(String(256))
    department_key: Mapped[str | None] = mapped_column(String(256))
    year: Mapped[int | None] = mapped_column(Integer)
    week: Mapped[int | None] = mapped_column(Integer)
    main_comment: Mapped[str | None] = mapped_column(Text)
    day_comments: Mapped[dict[str, Any]] = mapped_column(default=dict)
