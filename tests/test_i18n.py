"""Mecanismo de i18n (Fase 5): catálogo completo de textos y valores.

Regla DAT-001: ningún valor real desaparece por no tener traducción; se devuelve tal cual.
"""

from __future__ import annotations

from mia.auth import UserContext
from mia.conversation import ToolStatus
from mia.core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, t, translate_value
from mia.ingestion.mappers.hr import ShiftKind
from mia.modules.rrhh.common import no_population


def test_supported_languages_and_default() -> None:
    assert SUPPORTED_LANGUAGES == ("es", "en")
    assert DEFAULT_LANGUAGE == "es"


def test_user_context_defaults_to_spanish() -> None:
    """Nadie rellena todavía la preferencia real del usuario: por ahora siempre «es»."""
    assert UserContext("u", "Nombre").language == "es"


# ------------------------------------------------------------------ t(): textos de la aplicación


def test_app_text_in_spanish_matches_the_existing_message_exactly() -> None:
    """El mismo texto que ya devuelve hoy common.no_population(): cablearlo no cambiaría nada."""
    assert t("errors.no_previous_population") == "No hay un resultado anterior con personas sobre el que cruzar."


def test_app_text_in_english() -> None:
    assert (
        t("errors.no_previous_population", lang="en") == "There is no previous result with people to cross-reference."
    )


def test_app_text_with_params() -> None:
    assert t("errors.department_not_found", lang="es", query="Pisos") == "No existe el departamento «Pisos»."
    assert t("errors.department_not_found", lang="en", query="Pisos") == 'There is no department called "Pisos".'


def test_unknown_key_falls_back_to_the_key_itself() -> None:
    """Mejor un hueco visible (DAT-001: nunca ocultar que falta un dato) que un error."""
    assert t("no.registrada.todavia") == "no.registrada.todavia"


def test_person_not_found_message() -> None:
    assert t("errors.person_not_found", query="Juanito") == "No hay ninguna persona que encaje con «Juanito»."
    assert t("errors.person_not_found", lang="en", query="Juanito") == 'No person matches "Juanito".'


def test_person_ambiguous_message() -> None:
    assert t("errors.person_ambiguous") == "Hay varias personas que encajan: pregunta cuál antes de continuar."
    assert t("errors.person_ambiguous", lang="en") == "Several people match: ask which one before continuing."


def test_no_previous_table_message() -> None:
    assert t("errors.no_previous_table") == "No hay un resultado en tabla anterior sobre el que operar."
    assert t("errors.no_previous_table", lang="en") == "There is no previous table result to operate on."


def test_freshness_messages() -> None:
    assert t("freshness.stale", minutes=45) == "Última sincronización hace 45 minutos: pueden faltar cambios recientes."
    assert t("freshness.stale", lang="en", minutes=45) == "Last synced 45 minutes ago: recent changes may be missing."
    assert (
        t("freshness.never_synced", sources="Turnos, Vacaciones")
        == "Estas fuentes no se han sincronizado nunca: Turnos, Vacaciones"
    )


def test_table_labels_spanish() -> None:
    assert t("labels.name") == "Nombre"
    assert t("labels.department") == "Departamento"
    assert t("labels.position") == "Puesto"
    assert t("labels.active") == "Activo"
    assert t("labels.inactive") == "Inactivo"
    assert t("labels.yes") == "Sí"
    assert t("labels.no") == "No"


def test_table_labels_english() -> None:
    assert t("labels.name", lang="en") == "Name"
    assert t("labels.department", lang="en") == "Department"
    assert t("labels.position", lang="en") == "Position"
    assert t("labels.active", lang="en") == "Active"
    assert t("labels.inactive", lang="en") == "Inactive"
    assert t("labels.yes", lang="en") == "Yes"
    assert t("labels.no", lang="en") == "No"


# ------------------------------------------------------------------ translate_value(): valores de vacaciones


def test_vacation_status_value_in_spanish_is_the_literal_source_value() -> None:
    """En español, traducir no cambia ni un carácter de lo que ya manda SharePoint."""
    assert translate_value("estado_vacaciones", "Pendiente Firma") == "Pendiente Firma"
    assert translate_value("estado_vacaciones", "Aceptada") == "Aceptada"


def test_vacation_status_value_in_english() -> None:
    assert translate_value("estado_vacaciones", "Pendiente Firma", lang="en") == "Pending signature"
    assert translate_value("estado_vacaciones", "Rechazada", lang="en") == "Rejected"
    assert translate_value("estado_vacaciones", "Aprobada", lang="en") == "Approved"
    assert translate_value("estado_vacaciones", "Pendiente", lang="en") == "Pending"
    assert translate_value("estado_vacaciones", "Aceptada", lang="en") == "Accepted"


# ------------------------------------------------------------------ translate_value(): tipo_turno (ShiftKind)


def test_all_shift_kinds_are_in_catalog() -> None:
    """Todos los ShiftKind definidos en hr.py tienen entrada en el catálogo."""
    all_kinds = [
        ShiftKind.TRABAJO,
        ShiftKind.DESCANSO,
        ShiftKind.VACACIONES,
        ShiftKind.BAJA,
        ShiftKind.ASUNTOS_PROPIOS,
        ShiftKind.PERMISO,
        ShiftKind.FESTIVO,
        ShiftKind.SIN_PUBLICAR,
        ShiftKind.OTRO,
    ]
    for kind in all_kinds:
        result = translate_value("tipo_turno", kind)
        assert result == kind, f"El ShiftKind {kind!r} no está en el catálogo tipo_turno"


def test_shift_kind_value_in_english() -> None:
    assert translate_value("tipo_turno", "Baja/IT", lang="en") == "Sick leave"
    assert translate_value("tipo_turno", "Vacaciones", lang="en") == "Vacation"
    assert translate_value("tipo_turno", "Trabajo", lang="en") == "Work"
    assert translate_value("tipo_turno", "Descanso", lang="en") == "Day off"
    assert translate_value("tipo_turno", "Festivo", lang="en") == "Public holiday"
    assert translate_value("tipo_turno", "Permiso", lang="en") == "Leave of absence"
    assert translate_value("tipo_turno", "Asuntos propios", lang="en") == "Personal leave"
    assert translate_value("tipo_turno", "Sin publicar", lang="en") == "Not published yet"
    assert translate_value("tipo_turno", "Otro", lang="en") == "Other"


# ------------------------------------------------------------------ translate_value(): tipo_solicitud


def test_request_type_in_spanish_is_unchanged() -> None:
    assert translate_value("tipo_solicitud", "Vacaciones") == "Vacaciones"
    assert translate_value("tipo_solicitud", "Asuntos propios") == "Asuntos propios"


def test_request_type_in_english() -> None:
    assert translate_value("tipo_solicitud", "Vacaciones", lang="en") == "Vacation"
    assert translate_value("tipo_solicitud", "Asuntos propios", lang="en") == "Personal leave"
    assert translate_value("tipo_solicitud", "Permiso", lang="en") == "Leave of absence"
    assert translate_value("tipo_solicitud", "Baja", lang="en") == "Sick leave"


# ------------------------------------------------------------------ translate_value(): dia_semana


def test_weekday_codes_in_spanish() -> None:
    assert translate_value("dia_semana", "L") == "Lunes"
    assert translate_value("dia_semana", "M") == "Martes"
    assert translate_value("dia_semana", "X") == "Miércoles"
    assert translate_value("dia_semana", "J") == "Jueves"
    assert translate_value("dia_semana", "V") == "Viernes"
    assert translate_value("dia_semana", "S") == "Sábado"
    assert translate_value("dia_semana", "D") == "Domingo"


def test_weekday_codes_in_english() -> None:
    assert translate_value("dia_semana", "L", lang="en") == "Monday"
    assert translate_value("dia_semana", "D", lang="en") == "Sunday"
    assert translate_value("dia_semana", "S", lang="en") == "Saturday"


# ------------------------------------------------------------------ translate_value(): estado_empleado


def test_employee_status_labels() -> None:
    assert translate_value("estado_empleado", "Activo") == "Activo"
    assert translate_value("estado_empleado", "Inactivo") == "Inactivo"
    assert translate_value("estado_empleado", "Activo", lang="en") == "Active"
    assert translate_value("estado_empleado", "Inactivo", lang="en") == "Inactive"


# ------------------------------------------------------------------ casos límite


def test_unknown_or_missing_value_passes_through_unchanged() -> None:
    """Un dato real nunca desaparece por no tener traducción todavía (DAT-001)."""
    assert translate_value("estado_vacaciones", "Caducada") == "Caducada"
    assert translate_value("estado_vacaciones", "Caducada", lang="en") == "Caducada"
    assert translate_value("estado_vacaciones", None) is None


def test_wiring_in_common_no_population() -> None:
    """no_population() usa t() — en español el resultado es idéntico al hardcodeado anterior."""
    result = no_population()
    assert result.status is ToolStatus.NOT_FOUND
    assert result.summary == "No hay un resultado anterior con personas sobre el que cruzar."
