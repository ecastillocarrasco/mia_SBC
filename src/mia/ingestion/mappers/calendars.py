"""Transformaciones de la planificación v12: Calendario<Departamento>_AAAA (histórico real),
TipoTurnos (catálogo), TurnosPlantillas (reglas de generación) y ComentariosTurnosSemanas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mia.ingestion.mappers.common import MapContext, boolean, number, sp_datetime, text
from mia.text import normalize_key

Row = dict[str, Any]
MADRID = ZoneInfo("Europe/Madrid")
DAY_FIELDS = (
    ("L", "Horario_L"),
    ("M", "Horario_M"),
    ("X", "Horario_X"),
    ("J", "Horario_J"),
    ("V", "Horario_V"),
    ("S", "Horario_S"),
    ("D", "Horario_D"),
)
OFF_WORDS = {"off", "libre", "descanso"}


def _local(value: Any) -> datetime | None:
    parsed = sp_datetime(value)
    return parsed.astimezone(MADRID) if parsed else None


def shift_kind(description: str | None, hours: float | None) -> str:
    """Mismo criterio que el sistema anterior: OFF/sin asignación/0 horas no cuentan como trabajo."""
    key = normalize_key(description)
    if key in OFF_WORDS:
        return "off"
    if "sin asignacion" in key:
        return "unassigned"
    if hours and hours > 0:
        return "work"
    return "special" if description else "unknown"


def calendar_shift(department: str, year: int) -> Any:
    def mapper(item: dict[str, Any], ctx: MapContext) -> list[Row]:
        start = _local(item.get("StartDate"))
        end = _local(item.get("EndDate"))
        if start is None:
            return []
        description = text(item.get("DescripcionTurno"))
        hours = number(item.get("HorasTotalesTurno"))
        if hours is None and end is not None and normalize_key(description) not in OFF_WORDS:
            span = (end - start).total_seconds() / 3600
            hours = round(span, 2) if 0 < span <= 16 else None  # eventos de día completo no son horas
        return [
            {
                "sp_id": int(item["ID"]),
                "department": department,
                "department_key": normalize_key(department),
                "year": year,
                "employee_name": text(item.get("EmpleadoTurno")),
                "employee_name_key": normalize_key(item.get("EmpleadoTurno")) or None,
                "day": start.date(),
                "start_at": start,
                "end_at": end,
                "description": description,
                "comment": text(item.get("ComentariosTurno")) or text(item.get("Comments")),
                "hours_total": hours,
                "hours_night": number(item.get("HorasNocturnas")),
                "split_shift": boolean(item.get("TurnoPartido")),
                "kind": shift_kind(description, hours),
                "week": int(week)
                if str(item.get("SemanaTurno") or "").strip().isdigit() and (week := item["SemanaTurno"])
                else None,
                "last_published_at": sp_datetime(item.get("UltimaPublicacion")),
                "publication_count": int(n) if (n := number(item.get("ContPublicacion"))) is not None else None,
                "report_sent": boolean(item.get("InformeTurnoEnviado"))
                if item.get("InformeTurnoEnviado") is not None
                else None,
                "created_at": sp_datetime(item.get("Created")),
                "modified_at": sp_datetime(item.get("Modified")),
            }
        ]

    return mapper


def hhmm(value: Any) -> str | None:
    """«07:00» o «7:00» → «07:00»; basura como «0:undefined» → None (fallo real en TipoTurnos)."""
    raw = text(value)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw or "")
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def shift_type(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    department = text(item.get("DepartamentoTurno"))
    return [
        {
            "sp_id": int(item["ID"]),
            "code": (text(item.get("Title")) or f"Tipo {item['ID']}")[:64],
            "department": department,
            "department_key": normalize_key(department) or None,
            "description": text(item.get("DescripcionTurno")),
            "start1": hhmm(item.get("HorarioInicio")),
            "end1": hhmm(item.get("HorarioFin")),
            "start2": hhmm(item.get("HorarioInicio2")),
            "end2": hhmm(item.get("HorarioFin2")),
            "hours_total": number(item.get("HorasTotalesTurno")),
            "hours_night": number(item.get("HorasNocturnas")),
            "split_shift": boolean(item.get("TurnoPartido")),
        }
    ]


def shift_template(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    from mia.ingestion.mappers.common import sp_local_date  # noqa: PLC0415

    department = text(item.get("DepartamentoTurno"))
    schedule = {code: text(item.get(field)) for code, field in DAY_FIELDS if text(item.get(field))}
    return [
        {
            "sp_id": int(item["ID"]),
            "department": department,
            "department_key": normalize_key(department) or None,
            "employee_name": text(item.get("EmpleadoTurno")),
            "employee_name_key": normalize_key(item.get("EmpleadoTurno")) or None,
            "template_start": sp_local_date(item.get("FechaInicioPlantilla"), ctx.tz),
            "template_end": sp_local_date(item.get("FechaFinPlantilla"), ctx.tz),
            "anchor_date": sp_local_date(item.get("FechaTurno"), ctx.tz),
            "schedule": schedule,
            "comment": text(item.get("ComentariosTurno")),
            "split_count": int(n) if (n := number(item.get("Num_Turnos_Partidos"))) is not None else None,
            "night_hours": number(item.get("Totales_Horas_Nocturnas")),
            "week": int(n) if (n := number(item.get("SemanaTurno"))) is not None else None,
        }
    ]


def week_comment(item: dict[str, Any], ctx: MapContext) -> list[Row]:
    department = text(item.get("DepartamentoTurno"))
    days = {
        code: text(item.get(f"ComentariosTurno{code}"))
        for code in "LMXJVSD"
        if text(item.get(f"ComentariosTurno{code}"))
    }
    return [
        {
            "sp_id": int(item["ID"]),
            "department": department,
            "department_key": normalize_key(department) or None,
            "year": int(n) if (n := number(item.get("AnnoTurno"))) is not None else None,
            "week": int(n) if (n := number(item.get("SemanaTurno"))) is not None else None,
            "main_comment": text(item.get("ComentariosTurnoPpal")),
            "day_comments": days,
        }
    ]
