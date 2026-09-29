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


_LABEL_WORDS = {
    "nominas": "nóminas",
    "nomina": "nómina",
    "leidas": "leídas",
    "leidos": "leídos",
    "leida": "leída",
    "dias": "días",
    "anio": "año",
    "anios": "años",
    "telefono": "teléfono",
    "codigo": "código",
    "situacion": "situación",
    "organizacion": "organización",
    "documentacion": "documentación",
    "proximos": "próximos",
    "proximas": "próximas",
    "proximo": "próximo",
    "proxima": "próxima",
    "ultima": "última",
    "ultimo": "último",
    "cumpleanos": "cumpleaños",
    "medico": "médico",
    "prevencion": "prevención",
    "informacion": "información",
    "duracion": "duración",
    "maximo": "máximo",
    "minimo": "mínimo",
    "numero": "número",
    "periodo": "período",
    "periodos": "períodos",
    "tecnico": "técnico",
    "calculada": "calculada",
    "reincorporacion": "reincorporación",
    "direccion": "dirección",
}
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def humanize_label(key: object) -> str:
    """«nominas_no_leidas» → «Nóminas no leídas»: etiqueta legible y con tildes para pantalla e informes."""
    words = _CAMEL.sub(" ", str(key)).replace("_", " ").split()
    if not words:
        return ""
    fixed = [_LABEL_WORDS.get(w.lower(), w.lower()) if w.upper() != w or len(w) > 3 else w for w in words]
    text = " ".join(fixed)
    return text[:1].upper() + text[1:]
