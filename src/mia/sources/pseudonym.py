"""Seudonimización de identificadores personales.

El DNI/NIE nunca se almacena. Se guarda un HMAC-SHA256 con una clave secreta
(Key Vault), que permite unir listas (Empleados ↔ Turnos) sin conocer el dato.
"""

from __future__ import annotations

import hashlib
import hmac
import re

_CLEAN = re.compile(r"[^0-9A-Za-z]")


class Pseudonymizer:
    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("La clave de seudonimización no puede estar vacía")
        self._key = key.encode()

    def __call__(self, value: object) -> str | None:
        cleaned = _CLEAN.sub("", str(value or "")).upper()
        if not cleaned:
            return None
        return hmac.new(self._key, cleaned.encode(), hashlib.sha256).hexdigest()[:32]
