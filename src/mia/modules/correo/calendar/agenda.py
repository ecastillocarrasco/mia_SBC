"""Fechas locales y cálculo determinista de agenda y huecos."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mia.modules.correo.calendar.models import CalendarError, CalendarEvent
from mia.text import normalize_key

WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def local_datetime(value: datetime, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    if value.tzinfo is not None:
        return value.astimezone(zone)
    first = value.replace(tzinfo=zone, fold=0)
    second = value.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise CalendarError("Hora ambigua o inexistente por cambio horario; indica un desplazamiento UTC explícito")
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != value:
        raise CalendarError("La hora local no existe por el cambio horario")
    return first


def interval(period: str, now: datetime, timezone: str) -> tuple[datetime, datetime]:
    text = normalize_key(period)
    base = text.replace(" por la tarde", "").replace(" por la manana", "").strip()
    today = now.astimezone(ZoneInfo(timezone)).date()
    day = today
    days = 1
    if base in {"hoy", "proxima reunion", "proxima"}:
        if base != "hoy":
            return now.astimezone(ZoneInfo(timezone)), datetime.combine(
                today + timedelta(days=30), time(), ZoneInfo(timezone)
            )
    elif base == "manana":
        day += timedelta(days=1)
    elif base == "pasado manana":
        day += timedelta(days=2)
    elif text in {"esta semana", "semana", "semana que viene", "proxima semana"}:
        day -= timedelta(days=today.weekday())
        if text in {"semana que viene", "proxima semana"}:
            day += timedelta(days=7)
        days = 7
    else:
        matched = next((i for i, weekday in enumerate(WEEKDAYS) if re.search(rf"\b{weekday}\b", text)), None)
        if matched is not None:
            day += timedelta(days=(matched - today.weekday()) % 7)
        else:
            try:
                day = date.fromisoformat(text.split()[0])
            except (ValueError, IndexError) as exc:
                raise CalendarError("Indica un día ISO, hoy, mañana, un día de semana o una semana concreta") from exc
    start = datetime.combine(day, time(), ZoneInfo(timezone))
    end = datetime.combine(day + timedelta(days=days), time(), ZoneInfo(timezone))
    if "tarde" in text:
        start = start.replace(hour=15)
        end = start.replace(hour=20)
    elif "por la manana" in text:
        start = start.replace(hour=8)
        end = start.replace(hour=14)
    return start, end


def free_slots(events: list[CalendarEvent], start: datetime, end: datetime) -> list[dict[str, str]]:
    cursor = start
    slots = []
    for event in sorted(events, key=lambda item: item.start):
        if event.status == "cancelled" or event.availability in {"free", "workingElsewhere"}:
            continue
        if event.end <= cursor or event.start >= end:
            continue
        if event.start > cursor:
            slots.append({"start": cursor.isoformat(), "end": min(event.start, end).isoformat()})
        cursor = max(cursor, event.end)
        if cursor >= end:
            break
    if cursor < end:
        slots.append({"start": cursor.isoformat(), "end": end.isoformat()})
    return slots


def overlaps(events: list[CalendarEvent]) -> list[list[str]]:
    busy = [event for event in events if event.status != "cancelled" and event.availability != "free"]
    return [[a.id, b.id] for i, a in enumerate(busy) for b in busy[i + 1 :] if a.start < b.end and b.start < a.end]


def direct_agenda_period(message: str) -> str | None:
    """Recognize only an explicit, unfiltered request for the user's own agenda."""
    query = normalize_key(message).removeprefix("por favor ").removesuffix(" por favor")
    match = re.fullmatch(
        r"(?:(?:muestrame|muestra|ensename|ensena|dime|consulta|ver|lista) )?"
        r"mi (?:agenda|calendario|reuniones)(?: de| para)? "
        r"(hoy|manana|pasado manana|esta semana|proxima semana|semana que viene)",
        query,
    )
    return match[1] if match else None
