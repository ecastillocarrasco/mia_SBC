"""Explicit calendar-week scope shared by read tools; no inferred authorization."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from mia.text import normalize_key


def requested_week(message: str, today: date) -> tuple[date, date] | None:
    expressions = re.findall(
        r"\b(esta semana|semana actual|proxima semana|semana que viene|la semana pasada|semana pasada)\b",
        normalize_key(message),
    )
    if len(expressions) != 1:
        return None
    expression = expressions[0]
    offset = 7 if expression in {"proxima semana", "semana que viene"} else -7 if "pasada" in expression else 0
    monday = today - timedelta(days=today.weekday()) + timedelta(days=offset)
    return monday, monday + timedelta(days=6)


def validate_week_arguments(arguments: Mapping[str, Any], message: str, today: date) -> None:
    week = requested_week(message, today)
    if week is None:
        return
    for key, expected in zip(("desde", "hasta"), week, strict=True):
        value = arguments.get(key)
        if value is not None and str(value) != expected.isoformat():
            raise ValueError(f"La semana solicitada requiere {key}={expected.isoformat()}")
