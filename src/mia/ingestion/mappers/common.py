"""Utilidades comunes para transformar elementos de SharePoint en filas canónicas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from mia.ingestion.pseudonym import Pseudonymizer
from mia.text import normalize_key


@dataclass(frozen=True, slots=True)
class MapContext:
    tz: ZoneInfo
    pseudonymize: Pseudonymizer
    year: int | None = None
    exclude_name: tuple[re.Pattern[str], ...] = ()
    """Cuentas que no son personas reales (de prueba): el mapper las descarta."""

    def is_excluded(self, name: str | None) -> bool:
        key = normalize_key(name)
        return bool(key) and any(p.search(key) for p in self.exclude_name)


def text(value: Any) -> str | None:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def email(value: Any) -> str | None:
    cleaned = text(value)
    return cleaned.lower() if cleaned else None


def boolean(value: Any) -> bool:
    """Campo Sí/No de SharePoint: True/1/"Sí" = activo (semántica validada en el sistema anterior)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    return str(value or "").strip().lower() in {"true", "1", "yes", "si", "sí"}


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def sp_datetime(value: Any) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def sp_local_date(value: Any, tz: ZoneInfo) -> date | None:
    """Fecha de SharePoint (UTC) como fecha local: 2026-08-02T22:00:00Z → 03/08/2026 en Madrid."""
    moment = sp_datetime(value)
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(tz).date()


def ddmmyyyy(value: Any) -> date | None:
    """Fecha de texto DD/MM/AAAA; se ignora cualquier hora."""
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.strptime(raw.split(" ", 1)[0], "%d/%m/%Y").date()
    except ValueError:
        return None


def hyperlink_field(value: Any) -> str | None:
    """Campo "Hyperlink or Picture" de SharePoint (enlace o imagen) → su URL.

    La API REST lo devuelve como ``{"Url": ..., "Description": ...}``; se descarta la
    descripción (a menudo repite la propia URL o un texto sin valor añadido)."""
    if isinstance(value, dict):
        return text(value.get("Url"))
    return text(value)


def person_field(value: Any) -> tuple[str | None, str | None]:
    """Campo Persona expandido de SharePoint → (nombre, email)."""
    if isinstance(value, dict):
        return text(value.get("Title")), email(value.get("EMail") or value.get("Email"))
    return None, None


def people_field(value: Any) -> list[dict[str, str | None]]:
    """Campo Persona múltiple: lista, ``{"results": [...]}`` o un único objeto."""
    items: list[Any]
    if isinstance(value, dict):
        results = value.get("results")
        items = results if isinstance(results, list) else [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    people = []
    for item in items:
        if isinstance(item, dict):
            name, mail = person_field(item)
            people.append({"name": name, "email": mail})
    return people
