"""Logging estructurado (JSON en Azure, legible en local)."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from mia.observability.context import current_request_id

_SENSITIVE_KEYS = frozenset({"api_key", "authorization", "password", "secret", "token"})


def _add_request_id(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    request_id = current_request_id()
    if request_id:
        event.setdefault("request_id", request_id)
    return event


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in _SENSITIVE_KEYS:
            event[key] = "***"
    return event


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    # structlog (a diferencia del logging estándar) escribe con un print() crudo, sin la
    # tolerancia a errores de codificación que sí tiene logging.StreamHandler -- en Windows,
    # donde la consola suele ir en cp1252, un solo carácter fuera de esa página (acentos reales
    # de SharePoint, o los propios símbolos ✓/≈/✗/→ usados en 386 sitios de este código) hace
    # que el propio log.exception(...) de un error reviente con UnicodeEncodeError, saltándose
    # la red de seguridad de ToolRegistry._run que debería convertirlo en un ToolStatus.ERROR
    # limpio (incidencia real en preprod 2026-10-26). errors="replace" en vez de dejarlo fallar:
    # algunos lanzadores de servicio en Windows exponen un stdout sin .reconfigure() (poco común,
    # pero no debe impedir que arranque el resto del logging).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    # httpx registra cada petición con la URL completa: demasiado ruido (y datos) en INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False) if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_request_id,
            _redact,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
