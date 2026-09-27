"""Transformaciones de las listas de RRHH al modelo canónico.

Cada función recibe un elemento de SharePoint y devuelve las filas que le
corresponden. Las reglas proceden del sistema anterior, aquí explícitas y testeadas.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from mia.sources.mappers.common import (
    MapContext,
    boolean,
    ddmmyyyy,
    email,
    number,
    people_field,
    person_field,
    sp_datetime,
    sp_local_date,
    text,
)
from mia.text import normalize_key

Row = dict[str, Any]


def employee(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    manager_name, manager_email = person_field(item.get("Responsable"))
    name = text(item.get("Nombre")) or ""
    department = text(item.get("Departamento"))
    return [
        {
            "sp_id": int(item["ID"]),
            "employee_code": text(item.get("EmpleadoId")),
            "name": name,
            "name_key": normalize_key(name),
            "active": boolean(item.get("Activo")),
            "department": department,
            "department_key": normalize_key(department) or None,
            "position": text(item.get("Puesto")),
            "birth_date": ddmmyyyy(item.get("FechaNacimiento")),
            "email": email(item.get("Email")),
            "phone": text(item.get("Telefono")),
            "account": text(item.get("Cuenta")),
            "person_key": text(item.get("DocIdentidad")),  # ya seudonimizado en la ingesta
            "manager_name": manager_name,
            "manager_email": manager_email,
            "nationality": text(item.get("Nacionalidad")),
        }
    ]


def org_unit(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    department = text(item.get("AreaDepartamento"))
    section = text(item.get("Title"))
    return [
        {
            "sp_id": int(item["ID"]),
            "department": department,
            "department_key": normalize_key(department) or None,
            "section": section,
            "section_key": normalize_key(section) or None,
            "section_mail": email(item.get("MailDepartamento")),
            "department_mails": text(item.get("MailAreaDepartamento")),
            "managers": people_field(item.get("ResponsablesDepartamento")),
        }
    ]


# ------------------------------------------------------------------ turnos
WEEKDAYS = (("L", 1), ("M", 2), ("X", 3), ("J", 4), ("V", 5), ("S", 6), ("D", 7))
_HOURS = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")


class ShiftKind:
    TRABAJO = "Trabajo"
    DESCANSO = "Descanso"
    VACACIONES = "Vacaciones"
    BAJA = "Baja/IT"
    ASUNTOS_PROPIOS = "Asuntos propios"
    PERMISO = "Permiso"
    FESTIVO = "Festivo"
    SIN_PUBLICAR = "Sin publicar"
    OTRO = "Otro"


_KIND_RULES: tuple[tuple[Callable[[str], bool], str], ...] = (
    (lambda k: "vacacion" in k, ShiftKind.VACACIONES),
    (lambda k: k in {"off", "libre"} or "descanso" in k, ShiftKind.DESCANSO),
    (lambda k: "baja" in k or f" {k} ".find(" it ") >= 0, ShiftKind.BAJA),
    (lambda k: "asunto" in k and "propio" in k, ShiftKind.ASUNTOS_PROPIOS),
    (lambda k: "permiso" in k, ShiftKind.PERMISO),
    (lambda k: "festiv" in k, ShiftKind.FESTIVO),
)


def shift_kind(value: Any) -> str:
    """Clasificación del texto de un turno (misma semántica que el sistema anterior)."""
    raw = str(value or "").strip()
    if not raw:
        return ShiftKind.SIN_PUBLICAR
    key = normalize_key(raw)
    for matches, kind in _KIND_RULES:
        if matches(key):
            return kind
    if _HOURS.search(raw) or "|" in raw:
        return ShiftKind.TRABAJO
    return ShiftKind.OTRO


def shift_segments(raw: str | None) -> list[tuple[str, str]]:
    """Todos los tramos de un turno: «10:00-14:00 / 18:00-22:00» → dos tramos (turno partido)."""
    return [(a.zfill(5), b.zfill(5)) for a, b in _HOURS.findall(raw or "")]


def shift_hours(segments: list[tuple[str, str]]) -> float:
    """Horas del turno sumando tramos; los que cruzan medianoche se cuentan bien. DESCANSO no computa."""
    total = 0
    for start, end in segments:
        a = int(start[:2]) * 60 + int(start[3:])
        b = int(end[:2]) * 60 + int(end[3:])
        total += (b - a) % (24 * 60) or 24 * 60
    return round(total / 60, 2)


def _int(value: Any) -> int | None:
    raw = str(value or "").strip()
    return int(raw) if raw.isdigit() else None


def shift_week(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    """Una fila semanal de Turnos → siete días. Las carpetas (sin persona/año/semana) se descartan."""
    year, week = _int(item.get("AnnoTurno")), _int(item.get("SemanaTurno"))
    person_key = text(item.get("DNIEmpleado"))  # ya seudonimizado en la ingesta
    if not person_key or year is None or week is None:
        return []
    department = text(item.get("DepartamentoTurno"))
    rows: list[Row] = []
    for code, iso_day in WEEKDAYS:
        try:
            day = date.fromisocalendar(year, week, iso_day)
        except ValueError:
            return []
        raw = text(item.get(f"Turno_{code}"))
        segments = shift_segments(raw)
        area = (raw.split("|", 1)[0].strip() or None) if raw and "|" in raw else None
        rows.append(
            {
                "sp_item_id": int(item["ID"]),
                "day": day,
                "person_key": person_key,
                "employee_name": text(item.get("EmpleadoTurno")),
                "email": email(item.get("MailContacto")),
                "department": department,
                "department_key": normalize_key(department) or None,
                "iso_year": year,
                "iso_week": week,
                "weekday": code,
                "raw_value": raw,
                "kind": shift_kind(raw),
                "area": area,
                "start_time": segments[0][0] if segments else None,
                "end_time": segments[-1][1] if segments else None,
                "segments": ",".join(f"{a}-{b}" for a, b in segments) or None,
                "hours": shift_hours(segments) if shift_kind(raw) == ShiftKind.TRABAJO else 0.0,
                "comment": text(item.get(f"Comentarios_{code}")),
                "published_by": text(item.get("Publicador")),
            }
        )
    return rows


# ------------------------------------------------------------------ vacaciones
def vacation(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    name, mail = person_field(item.get("Empleado"))
    department = text(item.get("Departamento"))
    lookup = item.get("EmpleadoId")
    return [
        {
            "sp_id": int(item["ID"]),
            "employee_lookup_id": int(lookup) if isinstance(lookup, int | float) else None,
            "employee_name": name,
            "employee_email": mail,
            "department": department,
            "department_key": normalize_key(department) or None,
            "status": text(item.get("Estado")),
            "start_date": sp_local_date(item.get("FechaInicio"), ctx.tz),
            "end_date": sp_local_date(item.get("FechaFin"), ctx.tz),
            "total_days": number(item.get("DiasTotales")),
            "request_type": text(item.get("TipoSolicitud")),
            "responsible": text(item.get("Responsable")),
            "created_at": sp_datetime(item.get("Created")),
        }
    ]


def vacation_balance(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    if ctx.year is None:
        raise ValueError("El saldo de vacaciones requiere el año de la lista")
    name, mail = person_field(item.get("Empleado"))
    return [
        {
            "year": ctx.year,
            "sp_id": int(item["ID"]),
            "employee_name": name,
            "employee_email": mail,
            "department": text(item.get("Departamento")),
            # VAC-002: el saldo negativo se conserva tal cual; nunca se trunca a cero.
            "current_balance": number(item.get("SaldoActual")),
            "total_balance": number(item.get("SaldoTotal")),
            "modified_at": sp_datetime(item.get("Modified")),
        }
    ]
