"""Catálogo de fuentes sincronizadas.

Añadir una fuente = declarar aquí su lista, campos, tabla destino y transformación.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from mia.data import Employee, OrgUnit, ShiftDay, Vacation, VacationBalance
from mia.data.models import Base
from mia.sources.mappers import hr
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
    scope: dict[str, Any] = field(default_factory=dict)
    """Columnas fijas de esta fuente en la tabla canónica (p. ej. el año del saldo)."""
    year: int | None = None


EMPLEADOS = SourceDefinition(
    key="empleados",
    list_title="EmpleadosCorporativos",
    select=(
        "ID,Nombre,Activo,Departamento,FechaNacimiento,Puesto,Email,Telefono,Cuenta,DocIdentidad,EmpleadoId,"
        "Responsable/Title,Responsable/EMail"
    ),
    expand="Responsable",
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
    )


def all_sources(today: date | None = None) -> list[SourceDefinition]:
    """Fuentes activas. El saldo se sincroniza para el año en curso."""
    year = (today or date.today()).year
    return [EMPLEADOS, DEPARTAMENTOS, TURNOS, VACACIONES, saldo_vacaciones(year)]
