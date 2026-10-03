"""Mecanismo de i18n (paso 5 de la reestructuración): 3 ejemplos de que funciona.

No se ha cableado todavía en ningún dominio (esta reestructuración no toca lógica de negocio);
esta suite demuestra el mecanismo en sí: textos de la aplicación y valores de catálogo de dato,
en español (idéntico a lo que ya se muestra hoy) y en inglés.
"""

from __future__ import annotations

from mia.auth import UserContext
from mia.core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, t, translate_value


def test_supported_languages_and_default() -> None:
    assert SUPPORTED_LANGUAGES == ("es", "en")
    assert DEFAULT_LANGUAGE == "es"


def test_user_context_defaults_to_spanish() -> None:
    """Nadie rellena todavía la preferencia real del usuario: por ahora siempre «es»."""
    assert UserContext("u", "Nombre").language == "es"


# ------------------------------------------------------------------ ejemplo 1: texto de la aplicación
def test_app_text_in_spanish_matches_the_existing_message_exactly() -> None:
    """El mismo texto que ya devuelve hoy common.no_population(): cablearlo no cambiaría nada."""
    assert t("errors.no_previous_population") == "No hay un resultado anterior con personas sobre el que cruzar."


def test_app_text_in_english() -> None:
    assert t("errors.no_previous_population", lang="en") == "There is no previous result with people to cross-reference."


def test_app_text_with_params() -> None:
    assert t("errors.department_not_found", lang="es", query="Pisos") == "No existe el departamento «Pisos»."
    assert t("errors.department_not_found", lang="en", query="Pisos") == 'There is no department called “Pisos”.'


def test_unknown_key_falls_back_to_the_key_itself() -> None:
    """Mejor un hueco visible (CTX/DAT-001: nunca ocultar que falta un dato) que un error."""
    assert t("no.registrada.todavia") == "no.registrada.todavia"


# ------------------------------------------------------------------ ejemplo 2: valores de vacaciones
def test_vacation_status_value_in_spanish_is_the_literal_source_value() -> None:
    """En español, traducir no cambia ni un carácter de lo que ya manda SharePoint."""
    assert translate_value("estado_vacaciones", "Pendiente Firma") == "Pendiente Firma"
    assert translate_value("estado_vacaciones", "Aceptada") == "Aceptada"


def test_vacation_status_value_in_english() -> None:
    assert translate_value("estado_vacaciones", "Pendiente Firma", lang="en") == "Pending signature"
    assert translate_value("estado_vacaciones", "Rechazada", lang="en") == "Rejected"


# ------------------------------------------------------------------ ejemplo 3: valores de turno
def test_shift_kind_value_in_english() -> None:
    assert translate_value("tipo_turno", "Baja/IT", lang="en") == "Sick leave"
    assert translate_value("tipo_turno", "Vacaciones", lang="en") == "Vacation"


def test_unknown_or_missing_value_passes_through_unchanged() -> None:
    """Un dato real nunca desaparece por no tener traducción todavía (DAT-001)."""
    assert translate_value("estado_vacaciones", "Caducada") == "Caducada"
    assert translate_value("estado_vacaciones", "Caducada", lang="en") == "Caducada"
    assert translate_value("estado_vacaciones", None) is None
