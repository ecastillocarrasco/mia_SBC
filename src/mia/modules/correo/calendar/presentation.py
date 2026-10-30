"""Presentación de calendario y resúmenes con fechas y horas explícitas."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def display_time(value: str, timezone: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone))
    return instant.strftime("%d/%m/%Y a las %H:%M")


def describe_operation(operation: dict[str, Any]) -> dict[str, str]:
    original = operation.get("original", {})
    changes = operation.get("changes", {})
    timezone = operation["timezone"]
    result = {
        "accion": operation["action"],
        "asunto": changes.get("subject") or original.get("subject", "Reunión"),
        "zona_horaria": timezone,
    }
    for source, suffix in ((original, "actual"), (changes, "propuesto")):
        for field, label in (("start", "inicio"), ("end", "fin")):
            if source.get(field):
                result[f"{label}_{suffix}"] = display_time(source[field], timezone)
    return result


def calendar_view(events: list[dict[str, Any]], timezone: str, start: datetime, end: datetime) -> dict[str, Any]:
    zone = ZoneInfo(timezone)
    days = []
    day = start.astimezone(zone).date()
    last = (end.astimezone(zone) - timedelta(microseconds=1)).date()
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    while day <= last:
        days.append({"date": day.isoformat(), "label": f"{weekdays[day.weekday()]} {day:%d/%m}"})
        day += timedelta(days=1)
    items = []
    for event in events:
        begin = datetime.fromisoformat(event["start"]).astimezone(zone)
        finish = datetime.fromisoformat(event["end"]).astimezone(zone)
        items.append(
            {
                **event,
                "start_day": begin.date().isoformat(),
                "end_day": (finish - timedelta(microseconds=1)).date().isoformat(),
                "start_time": begin.strftime("%H:%M"),
                "end_time": finish.strftime("%H:%M"),
                "start_label": display_time(event["start"], timezone),
                "end_label": display_time(event["end"], timezone),
            }
        )
    return {
        "type": "calendar",
        "schema": "mia.calendar.presentation",
        "title": "Agenda",
        "timezone": timezone,
        "days": days,
        "events": items,
    }
