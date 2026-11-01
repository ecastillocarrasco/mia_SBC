"""Local projections of known structured fields before any external model call.

Field contracts supplement NER. They are not a claim that arbitrary prose is anonymous.
The input objects are copied; business data and local presentations remain intact.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any

_IDENTIFIERS = {
    "persona": "PERSON",
    "nombre": "PERSON",
    "name": "PERSON",
    "empleado": "PERSON",
    "email": "EMAIL_ADDRESS",
    "employee_email": "EMAIL_ADDRESS",
    "correo": "EMAIL_ADDRESS",
    "telefono": "PHONE_NUMBER",
    "phone": "PHONE_NUMBER",
    "dni": "ES_DNI_NIE",
    "nie": "ES_DNI_NIE",
    "nif": "ES_NIF",
    "iban": "ES_IBAN",
    "employee_id": "NRP",
    "empleado_id": "NRP",
    "person_key": "NRP",
    "referencia_poblacion": "NRP",
    "documento": "NRP",
}
_LOCAL_CONTENT = frozenset(
    {
        "texto",
        "contenido",
        "content",
        "body",
        "bodypreview",
        "extracto",
        "fragmento",
        "evidencia",
        "asunto",
        "subject",
        "diagnostico",
        "diagnóstico",
        "historial_medico",
        "historia_clinica",
        "tratamiento",
        "medicacion",
    }
)
LOCAL_CONTENT_MARKER = "<CONTENIDO_RESERVADO_EN_MIA>"


def protect_structured(
    text: str,
    tokenize: Callable[[str, str], str],
    *,
    reserve_content: bool,
) -> tuple[str, Counter[str]]:
    """Protect schema identifiers and reserve source text locally, including nested lists."""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return text, Counter()
    counts: Counter[str] = Counter()

    def walk(value: Any) -> Any:
        if isinstance(value, list):
            return [walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        if reserve_content:
            category = unicodedata.normalize("NFKD", str(value.get("tipo", value.get("doc_type", ""))))
            if "medic" in category.encode("ascii", "ignore").decode().casefold():
                return {"contenido_reservado": LOCAL_CONTENT_MARKER}
        result = {}
        for key, item in value.items():
            normalized = key.casefold()
            if reserve_content and normalized in _LOCAL_CONTENT:
                result[key] = LOCAL_CONTENT_MARKER
            elif normalized in _IDENTIFIERS and isinstance(item, (str, int)) and item != "":
                entity = _IDENTIFIERS[normalized]
                result[key] = tokenize(str(item), entity)
                counts[entity] += 1
            else:
                result[key] = walk(item)
        return result

    return json.dumps(walk(payload), ensure_ascii=False), counts
