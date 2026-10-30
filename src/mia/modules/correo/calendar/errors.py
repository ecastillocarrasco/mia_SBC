"""Diagnóstico seguro: códigos técnicos, nunca tokens ni cuerpos de respuesta."""

from mia.connectors.graph import GraphError
from mia.conversation import ToolResult, ToolStatus
from mia.diagnostics import EventStage, EventStatus, emit
from mia.observability import get_logger

log = get_logger(__name__)


def graph_failure(error: GraphError, tool: str) -> ToolResult:
    diagnostic = {
        "provider": "microsoft365",
        "tool": tool,
        "http_status": error.status_code,
        "error_code": error.code,
        "entra_codes": list(error.entra_codes),
        "calendar_scopes": list(error.calendar_scopes) if error.calendar_scopes is not None else None,
        "obo_client_id": error.obo_client_id,
    }
    emit(EventStage.GRAPH_CALL_ERROR, status=EventStatus.ERROR, data=diagnostic)
    log.warning("calendar.graph_error", **diagnostic)
    if error.status_code == 403:
        message = "Microsoft Graph ha denegado el acceso al calendario (HTTP 403)."
        action = (
            "Comprueba el permiso delegado Calendars.Read/Calendars.ReadWrite y su consentimiento "
            "en la aplicación API que hace OBO; el rol de mIA no concede permisos en Graph."
        )
    elif error.status_code == 401 or error.code in {"invalid_grant", "interaction_required", "missing_user_assertion"}:
        message = "No se pudo autorizar la sesión delegada para consultar el calendario."
        action = (
            "Revisa el código de Entra en diagnóstico; vuelve a iniciar sesión "
            "si requiere interacción o consentimiento."
        )
    elif error.code in {"invalid_client", "obo_not_configured", "unauthorized_client"}:
        message = "La autenticación OBO de la aplicación no ha podido completarse."
        action = "Revisa el certificado y la configuración del cliente API/OBO, sin cambiar a app-only."
    elif error.status_code == 404:
        message = "Microsoft Graph no encuentra el recurso de calendario solicitado (HTTP 404)."
        action = "Comprueba que la cuenta dispone de un buzón/calendario de Exchange accesible."
    else:
        message = "Microsoft Graph no ha podido completar la consulta de calendario."
        action = (
            "Revisa GRAPH_CALL_ERROR en diagnóstico para identificar el error "
            "antes de cambiar permisos o configuración."
        )
    return ToolResult(
        ToolStatus.SOURCE_UNAVAILABLE,
        {
            "mensaje": message,
            "diagnostico": diagnostic,
            "siguiente_paso": action,
            "instruccion": "Explica el fallo concreto y conserva el código técnico disponible. "
            "No lo presentes como ausencia de reuniones ni confirmes una causa que el código no demuestra.",
        },
    )
