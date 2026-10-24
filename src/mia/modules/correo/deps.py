"""Dependencias propias del dominio de correo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MailDeps:
    settings: Any = None
    graph: Any = None
    db: Any = None
