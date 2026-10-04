"""Normalización de texto para comparar nombres, departamentos, etc."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(value: object) -> str:
    """Minúsculas, sin tildes ni signos: "Ángela  Pérez-Ruiz" → "angela perez ruiz"."""
    text = unicodedata.normalize("NFKD", str(value or "").lower().strip())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", text).strip()
