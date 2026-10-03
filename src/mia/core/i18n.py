"""Español/inglés, como mínimo. Dos capas separadas, porque no son el mismo problema:

* **Textos de la aplicación** (``t``): el prompt de sistema, los mensajes de error, las
  etiquetas de la interfaz. Los escribe mIA, así que se traducen por clave estable.
* **Valores de los datos** (``translate_value``): lo que ya viene de la fuente en español
  (``Vacation.status == "Pendiente Firma"``, ``ShiftDay.kind == "Baja/IT"``…). Traducir la
  pregunta del usuario no basta si la respuesta repite el valor tal cual venía de SharePoint.

Hoy solo está relleno el español -las claves en inglés existen para demostrar que el mecanismo
funciona, no como traducción completa-; añadir inglés de verdad es rellenar las tablas de abajo,
nunca tocar el código que las usa. Ningún valor real desaparece por no tener traducción
todavía: se devuelve tal cual (mejor un texto sin traducir que un dato que falta, DAT-001).
"""

from __future__ import annotations

from mia.text import normalize_key

SUPPORTED_LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE = "es"

# ------------------------------------------------------------------ textos de la aplicación
_STRINGS: dict[str, dict[str, str]] = {
    "errors.department_not_found": {
        "es": "No existe el departamento «{query}».",
        "en": "There is no department called “{query}”.",
    },
    "errors.no_previous_population": {
        "es": "No hay un resultado anterior con personas sobre el que cruzar.",
        "en": "There is no previous result with people to cross-reference.",
    },
    "prompt.previous_result_hint": {
        "es": "Para «de esos/ellas», «quiénes son» o «cuántos son», usa sobre_resultado_anterior=true.",
        "en": "For “those/them”, “who are they” or “how many”, use sobre_resultado_anterior=true.",
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **params: object) -> str:
    """Un texto de la aplicación, en el idioma pedido.

    Si la clave no está registrada o el idioma no tiene esa clave, cae a español; si ni
    siquiera existe en español, se devuelve la propia clave (hueco visible, no un error).
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    return text.format(**params) if params else text


# ------------------------------------------------------------------ valores de los datos
# El valor «es» es literal el que manda la fuente hoy (SharePoint): traducirlo no debe
# cambiar ni un carácter de lo que ya se muestra en español.
_VALUES: dict[str, dict[str, dict[str, str]]] = {
    "estado_vacaciones": {
        "aceptada": {"es": "Aceptada", "en": "Accepted"},
        "aprobada": {"es": "Aprobada", "en": "Approved"},
        "pendiente firma": {"es": "Pendiente Firma", "en": "Pending signature"},
        "pendiente": {"es": "Pendiente", "en": "Pending"},
        "rechazada": {"es": "Rechazada", "en": "Rejected"},
    },
    "tipo_turno": {
        "trabajo": {"es": "Trabajo", "en": "Work"},
        "descanso": {"es": "Descanso", "en": "Day off"},
        "vacaciones": {"es": "Vacaciones", "en": "Vacation"},
        "baja it": {"es": "Baja/IT", "en": "Sick leave"},  # normalize_key convierte «/» en espacio
        "asuntos propios": {"es": "Asuntos propios", "en": "Personal leave"},
        "permiso": {"es": "Permiso", "en": "Leave of absence"},
        "festivo": {"es": "Festivo", "en": "Public holiday"},
        "sin publicar": {"es": "Sin publicar", "en": "Not published yet"},
    },
}


def translate_value(catalog: str, value: str | None, lang: str = DEFAULT_LANGUAGE) -> str | None:
    """Un valor de dato de ``catalog`` (p. ej. «estado_vacaciones»), en el idioma pedido.

    ``None`` sigue siendo ``None``. Un valor que no está en el catálogo (dato nuevo que la
    tabla todavía no cubre) se devuelve tal cual: nunca se oculta un valor real por falta
    de traducción.
    """
    if value is None:
        return None
    entry = _VALUES.get(catalog, {}).get(normalize_key(value))
    if entry is None:
        return value
    return entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or value
