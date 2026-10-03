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


# DNI (8 dígitos + letra) y NIE (X/Y/Z + 7 dígitos + letra).
_ID_SEGMENT = re.compile(r"^[XYZxyz]?\d{7,8}[A-Za-z]$")
_ID_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])[XYZxyz]?\d{7,8}[A-Za-z](?![A-Za-z0-9])")


def looks_like_id(value: str) -> bool:
    return bool(_ID_SEGMENT.match(value.strip()))


def mask_ids(text: str | None) -> str | None:
    """Oculta cualquier DNI/NIE dentro de un texto (p. ej. un nombre de fichero)."""
    return _ID_IN_TEXT.sub("[id]", text) if text else text


def pseudonymize_path(path: str, pseudonymize: Pseudonymizer) -> tuple[str, str | None]:
    """Sustituye las carpetas con nombre DNI/NIE por su seudónimo y devuelve también ese seudónimo."""
    person_key = None
    parts = []
    for segment in path.split("/"):
        if looks_like_id(segment):
            key = pseudonymize(segment)
            person_key = person_key or key
            parts.append(f"pk-{key}")
        else:
            parts.append(mask_ids(segment) or segment)
    return "/".join(parts), person_key
