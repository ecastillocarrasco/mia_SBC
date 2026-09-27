"""Catálogo de fuentes sincronizadas.

Añadir una fuente = declarar aquí su lista, campos, tabla destino y transformación.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from mia.data import (
    Candidate,
    CvDocument,
    DocumentTypeConfig,
    Employee,
    NewHire,
    OrgUnit,
    Payslip,
    ShiftDay,
    SignedDocument,
    TtCommunication,
    TtCompany,
    TtRate,
    TtTimesheet,
    TtWorker,
    Vacation,
    VacationBalance,
)
from mia.data.models import Base
from mia.sources.mappers import docs, hr
from mia.sources.mappers.common import MapContext

Mapper = Callable[[dict[str, Any], MapContext], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    key: str
    """Identificador estable de la fuente (tabla source_items y estado)."""
    list_title: str
    select: str
    model: type[Base]
    mapper: Mapper
    owner_column: str
    """Columna de la tabla canónica que guarda el ID del elemento de SharePoint."""
    expand: str | None = None
    sensitive_fields: tuple[str, ...] = ()
    """Identificadores personales: se seudonimizan antes de guardar nada."""
    optional_fields: tuple[str, ...] = ()
    """Columnas que pueden no existir todavía en la lista (se piden solo si existen)."""
    identity_folders: bool = False
    """Biblioteca con carpetas por DNI/NIE: se seudonimizan las rutas y se añade «_person_key»."""
    scope: dict[str, Any] = field(default_factory=dict)
    """Columnas fijas de esta fuente en la tabla canónica (p. ej. el año del saldo)."""
    year: int | None = None
    site: str = "rrhh"
    """Sitio de SharePoint: «rrhh» (por defecto) o «portal»."""
    domain: str = "empleados"
    """Dominio al que pertenece (si el dominio está desactivado, la fuente no se sincroniza)."""


EMPLEADOS = SourceDefinition(
    key="empleados",
    list_title="EmpleadosCorporativos",
    select=(
        "ID,Nombre,Activo,Departamento,FechaNacimiento,Puesto,Email,Telefono,Cuenta,DocIdentidad,EmpleadoId,"
        "Responsable/Title,Responsable/EMail"
    ),
    expand="Responsable",
    optional_fields=("Nacionalidad",),
    model=Employee,
    mapper=hr.employee,
    owner_column="sp_id",
    sensitive_fields=("DocIdentidad",),
)

DEPARTAMENTOS = SourceDefinition(
    key="departamentos",
    list_title="Departamentos",
    select=(
        "ID,Title,AreaDepartamento,MailDepartamento,MailAreaDepartamento,"
        "ResponsablesDepartamento/Title,ResponsablesDepartamento/EMail"
    ),
    expand="ResponsablesDepartamento",
    model=OrgUnit,
    mapper=hr.org_unit,
    owner_column="sp_id",
)

TURNOS = SourceDefinition(
    key="turnos",
    list_title="Turnos",
    select=(
        "ID,AnnoTurno,SemanaTurno,EmpleadoTurno,DepartamentoTurno,MailContacto,DNIEmpleado,"
        "Turno_L,Turno_M,Turno_X,Turno_J,Turno_V,Turno_S,Turno_D,"
        "Comentarios_L,Comentarios_M,Comentarios_X,Comentarios_J,Comentarios_V,Comentarios_S,Comentarios_D,"
        "Publicador,Modified"
    ),
    model=ShiftDay,
    mapper=hr.shift_week,
    owner_column="sp_item_id",
    sensitive_fields=("DNIEmpleado",),
    domain="turnos",
)

VACACIONES = SourceDefinition(
    key="vacaciones",
    list_title="Vacaciones",
    select=(
        "ID,Created,EmpleadoId,Departamento,Estado,FechaInicio,FechaFin,DiasTotales,"
        "Responsable,TipoSolicitud,Empleado/Title,Empleado/EMail"
    ),
    expand="Empleado",
    model=Vacation,
    mapper=hr.vacation,
    owner_column="sp_id",
    domain="vacaciones",
)


def saldo_vacaciones(year: int) -> SourceDefinition:
    return SourceDefinition(
        key=f"saldo_vacaciones_{year}",
        list_title=f"SaldoVacaciones_{year}",
        select="ID,Departamento,SaldoActual,SaldoTotal,Modified,Empleado/Title,Empleado/EMail",
        expand="Empleado",
        model=VacationBalance,
        mapper=hr.vacation_balance,
        owner_column="sp_id",
        scope={"year": year},
        year=year,
        domain="vacaciones",
    )


CURRICULUMS = SourceDefinition(
    key="curriculums",
    list_title="CurriculosVitae",
    select="ID,FirstName,Title,EMail,Telefono,DepartamentoCV,ExpPrevia,Idiomas,EstadoCV,ComentariosCV,Fecha,Created",
    model=Candidate,
    mapper=docs.candidate,
    owner_column="sp_id",
    domain="curriculums",
)

CV_DOCS = SourceDefinition(
    key="cv_docs",
    list_title="CVDocs",
    select="ID,FileSystemObjectType,FileLeafRef,FileRef,Modified",
    model=CvDocument,
    mapper=docs.cv_document,
    owner_column="sp_id",
    domain="curriculums",
)

NOMINAS = SourceDefinition(
    key="nominas",
    list_title="Nominas",
    select=(
        "ID,FileSystemObjectType,FileLeafRef,FileRef,FileDirRef,Title,MesNomina,Leido,Created,"
        "UsuarioNomina/Title,UsuarioNomina/EMail"
    ),
    expand="UsuarioNomina",
    model=Payslip,
    mapper=docs.payslip,
    owner_column="sp_id",
    identity_folders=True,
    domain="nominas",
)

DOCUMENTOS_FIRMADOS = SourceDefinition(
    key="documentos_firmados",
    list_title="DocumentosFirmadosV2",
    select="ID,FileSystemObjectType,FileLeafRef,FileRef,FileDirRef,Created",
    model=SignedDocument,
    mapper=docs.signed_document,
    owner_column="sp_id",
    identity_folders=True,
    domain="documentos",
)

TT_EMPRESAS = SourceDefinition(
    key="tt_empresas",
    list_title="EmpresasTT",
    select="ID,Title,CIFEmpresaTT,MailEmpresaTT,TelefonoEmpresaTT",
    model=TtCompany,
    mapper=docs.tt_company,
    owner_column="sp_id",
    domain="trabajo_temporal",
)

TT_TRABAJADORES = SourceDefinition(
    key="tt_trabajadores",
    list_title="EmpleadosTT",
    select=(
        "ID,NombreEmpleadoTT,ApellidosEmpleadoTT,DepartamentoEmpleadoTT,EmpresaTTEmpleadoTT,"
        "MailEmpleadoTT,TelefonoEmpleadoTT,VisibleEmpleadoTT"
    ),
    model=TtWorker,
    mapper=docs.tt_worker,
    owner_column="sp_id",
    domain="trabajo_temporal",
)

TT_BOLETINES = SourceDefinition(
    key="tt_boletines",
    list_title="BoletinesTT",
    select=(
        "ID,FechaBoletinTT,EmpleadoBoletinTT,IDEmpleadoBoletinTT,EmpresaBoletinTT,IDEmpresaBoletinTT,"
        "DepartamentoBoletinTT,EstadoBoletinTT,HoraEntradaBoletinTT,HoraSalidaBoletinTT,"
        "HorasNormalesBoletinTT,HorasNocturnasBoletinTT,HorasTotalesBoletinTT,DietaBoletinTT,ImporteBoletinTT"
    ),
    model=TtTimesheet,
    mapper=docs.tt_timesheet,
    owner_column="sp_id",
    domain="trabajo_temporal",
)


ALTAS = SourceDefinition(
    key="altas_empleados",
    list_title="AltaEmpleados",
    select="ID,Title,Created,Nombre,Apellidos,Departamento,Puesto,Mail,Usuario365,userAccount,DNI",
    model=NewHire,
    mapper=docs.new_hire,
    owner_column="sp_id",
    sensitive_fields=("DNI",),
    domain="empleados",
)

TT_TARIFAS = SourceDefinition(
    key="tt_tarifas",
    list_title="SettingsTT",
    select=(
        "ID,Title,HInicioNormal,HFinNormal,HInicioNocturna,HFinNocturna,PrecioHNormal,PrecioHNocturna,"
        "PrecioDieta,RecargoCortaDuracion"
    ),
    model=TtRate,
    mapper=docs.tt_rate,
    owner_column="sp_id",
    domain="trabajo_temporal",
)

TT_COMUNICACIONES = SourceDefinition(
    key="tt_comunicaciones",
    list_title="ComunicacionesBoletinesTT",
    select="ID,Title,FileSystemObjectType,FileLeafRef,Created",
    model=TtCommunication,
    mapper=docs.tt_communication,
    owner_column="sp_id",
    identity_folders=True,
    domain="trabajo_temporal",
)

TIPOS_FIRMA_RRHH = SourceDefinition(
    key="tipos_documentos_firma",
    list_title="TiposDocumentosFirma",
    select="ID,Title,FirmarTodas,ReqAutorizacion",
    model=DocumentTypeConfig,
    mapper=docs.document_type_config("rrhh"),
    owner_column="sp_id",
    scope={"site": "rrhh"},
    domain="documentos",
)

TIPOS_DOCUMENTO_PORTAL = SourceDefinition(
    key="tipos_documento_portal",
    list_title="TipoDocumento",
    select="ID,Title,ReqAutorizacion",
    model=DocumentTypeConfig,
    mapper=docs.document_type_config("portal"),
    owner_column="sp_id",
    scope={"site": "portal"},
    site="portal",
    domain="documentos",
)


def all_sources(
    today: date | None = None, domains: list[str] | None = None, *, portal: bool = True
) -> list[SourceDefinition]:
    """Fuentes de los dominios activos. El saldo se sincroniza para el año en curso."""
    year = (today or date.today()).year
    sources = [
        EMPLEADOS,
        DEPARTAMENTOS,
        TURNOS,
        VACACIONES,
        saldo_vacaciones(year),
        CURRICULUMS,
        CV_DOCS,
        NOMINAS,
        DOCUMENTOS_FIRMADOS,
        TT_EMPRESAS,
        TT_TRABAJADORES,
        TT_BOLETINES,
        ALTAS,
        TT_TARIFAS,
        TT_COMUNICACIONES,
        TIPOS_FIRMA_RRHH,
        TIPOS_DOCUMENTO_PORTAL,
    ]
    # Empleados y departamentos son la base de todos los cruces: siempre se sincronizan.
    base = {"empleados"}
    return [
        s
        for s in sources
        if (domains is None or s.domain in base or s.domain in domains) and (portal or s.site != "portal")
    ]
