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
    # errores: personas
    "errors.person_not_found": {
        "es": "No hay ninguna persona que encaje con «{query}».",
        "en": 'No person matches "{query}".',
    },
    "errors.person_ambiguous": {
        "es": "Hay varias personas que encajan: pregunta cuál antes de continuar.",
        "en": "Several people match: ask which one before continuing.",
    },
    # errores: departamentos
    "errors.department_not_found": {
        "es": "No existe el departamento «{query}».",
        "en": 'There is no department called "{query}".',
    },
    "errors.department_ambiguous": {
        "es": "Hay varios departamentos que encajan («{query}»).",
        "en": 'Several departments match "{query}".',
    },
    # errores: resultados anteriores
    "errors.no_previous_population": {
        "es": "No hay un resultado anterior con personas sobre el que cruzar.",
        "en": "There is no previous result with people to cross-reference.",
    },
    "errors.no_previous_table": {
        "es": "No hay un resultado en tabla anterior sobre el que operar.",
        "en": "There is no previous table result to operate on.",
    },
    # frescura de datos
    "freshness.never_synced": {
        "es": "Estas fuentes no se han sincronizado nunca: {sources}",
        "en": "These sources have never been synced: {sources}",
    },
    "freshness.stale": {
        "es": "Última sincronización hace {minutes} minutos: pueden faltar cambios recientes.",
        "en": "Last synced {minutes} minutes ago: recent changes may be missing.",
    },
    # etiquetas de tabla / interfaz
    "labels.name": {"es": "Nombre", "en": "Name"},
    "labels.department": {"es": "Departamento", "en": "Department"},
    "labels.position": {"es": "Puesto", "en": "Position"},
    "labels.date": {"es": "Fecha", "en": "Date"},
    "labels.start_date": {"es": "Inicio", "en": "Start"},
    "labels.end_date": {"es": "Fin", "en": "End"},
    "labels.days": {"es": "Días", "en": "Days"},
    "labels.status": {"es": "Estado", "en": "Status"},
    "labels.type": {"es": "Tipo", "en": "Type"},
    "labels.people": {"es": "Personas", "en": "People"},
    "labels.balance": {"es": "Saldo", "en": "Balance"},
    "labels.yes": {"es": "Sí", "en": "Yes"},
    "labels.no": {"es": "No", "en": "No"},
    "labels.active": {"es": "Activo", "en": "Active"},
    "labels.inactive": {"es": "Inactivo", "en": "Inactive"},
    # pista al modelo
    "prompt.previous_result_hint": {
        "es": "Para «de esos/ellas», «quiénes son» o «cuántos son», usa sobre_resultado_anterior=true.",
        "en": "For 'those/them', 'who are they' or 'how many', use sobre_resultado_anterior=true.",
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
    # ---- tipo de turno (ShiftKind en ingestion/mappers/hr.py) ----------------------------
    "tipo_turno": {
        "trabajo": {"es": "Trabajo", "en": "Work"},
        "descanso": {"es": "Descanso", "en": "Day off"},
        "vacaciones": {"es": "Vacaciones", "en": "Vacation"},
        "baja it": {"es": "Baja/IT", "en": "Sick leave"},  # normalize_key convierte «/» en espacio
        "asuntos propios": {"es": "Asuntos propios", "en": "Personal leave"},
        "permiso": {"es": "Permiso", "en": "Leave of absence"},
        "festivo": {"es": "Festivo", "en": "Public holiday"},
        "sin publicar": {"es": "Sin publicar", "en": "Not published yet"},
        "otro": {"es": "Otro", "en": "Other"},
    },
    # ---- estado de la solicitud de vacaciones (Vacation.status) -------------------------
    "estado_vacaciones": {
        "aceptada": {"es": "Aceptada", "en": "Accepted"},
        "aprobada": {"es": "Aprobada", "en": "Approved"},
        "pendiente firma": {"es": "Pendiente Firma", "en": "Pending signature"},
        "pendiente": {"es": "Pendiente", "en": "Pending"},
        "rechazada": {"es": "Rechazada", "en": "Rejected"},
    },
    # ---- tipo de solicitud (Vacation.request_type, campo TipoSolicitud de SharePoint) ---
    "tipo_solicitud": {
        "vacaciones": {"es": "Vacaciones", "en": "Vacation"},
        "asuntos propios": {"es": "Asuntos propios", "en": "Personal leave"},
        "permiso": {"es": "Permiso", "en": "Leave of absence"},
        "baja": {"es": "Baja", "en": "Sick leave"},
    },
    # ---- día de la semana (ShiftDay.weekday: código de una letra) -----------------------
    "dia_semana": {
        "l": {"es": "Lunes", "en": "Monday"},
        "m": {"es": "Martes", "en": "Tuesday"},
        "x": {"es": "Miércoles", "en": "Wednesday"},
        "j": {"es": "Jueves", "en": "Thursday"},
        "v": {"es": "Viernes", "en": "Friday"},
        "s": {"es": "Sábado", "en": "Saturday"},
        "d": {"es": "Domingo", "en": "Sunday"},
    },
    # ---- estado del empleado (boolean Employee.active como etiqueta de pantalla) --------
    "estado_empleado": {
        "activo": {"es": "Activo", "en": "Active"},
        "inactivo": {"es": "Inactivo", "en": "Inactive"},
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
