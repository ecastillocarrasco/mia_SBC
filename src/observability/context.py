"""Contexto por petición (identificador de correlación)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("mia_request_id", default=None)


def new_request_id(incoming: str | None = None) -> str:
    """Fija el identificador de la petición; reutiliza el entrante si es válido."""
    value = (incoming or "").strip()
    if not value or len(value) > 64 or not value.replace("-", "").isalnum():
        value = uuid.uuid4().hex
    _request_id.set(value)
    return value


def current_request_id() -> str | None:
    return _request_id.get()
