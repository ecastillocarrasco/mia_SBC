"""Integración opcional con Application Insights mediante OpenTelemetry."""

from __future__ import annotations

from mia.observability.logging import get_logger
from mia.settings import Settings

log = get_logger(__name__)


def configure_telemetry(settings: Settings) -> bool:
    secret = settings.observability.applicationinsights_connection_string
    if secret is None or not secret.get_secret_value():
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # noqa: PLC0415
    except ImportError:
        log.warning("telemetry.disabled", reason="falta el extra 'azure'")
        return False
    configure_azure_monitor(connection_string=secret.get_secret_value())
    log.info("telemetry.enabled", backend="application_insights")
    return True
