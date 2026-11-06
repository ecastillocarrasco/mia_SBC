"""Aviso por correo cuando un turno termina con un error real.

Transporte SMTP dedicado (``MIA_SMTP__*``), no Microsoft Graph: el error puede originarse en el
turno de cualquier usuario, y el envío de correo del dominio Correo depende siempre del token
delegado (OBO) de quien esté hablando con mIA en ese momento -- aquí no hay ningún usuario del
que depender (ver ``mia.connectors.graph``).
"""

from __future__ import annotations

import asyncio
import smtplib
import time
from email.message import EmailMessage

from mia.diagnostics.models import TraceRecord
from mia.observability import get_logger
from mia.settings import SmtpSettings

log = get_logger(__name__)

_last_sent_at: float = float("-inf")
"""``time.monotonic()`` no garantiza empezar cerca de 0 (en un proceso/contenedor recién
arrancado puede valer, p. ej., unos pocos cientos de segundos) — con un valor inicial de 0.0,
un reinicio reciente del servicio podía silenciar el primer aviso real si ocurría dentro de la
primera ventana de cooldown tras arrancar. ``-inf`` garantiza que el primer aviso nunca se
descarta por esto, sin alterar el cálculo de los siguientes (incidencia real: test en CI contra
un contenedor recién iniciado, con ``time.monotonic()`` por debajo del cooldown de prueba)."""


def _is_real_error(record: TraceRecord) -> bool:
    """Error real: el turno ENTERO fracasó (excepción no controlada, fallo del LLM, exportación
    incompleta...).

    Que una herramienta concreta devuelva SOURCE_UNAVAILABLE/PERMISSION_DENIED (p. ej. Graph
    responde 404 porque el usuario pidió un buzón que no existe) no es un fallo del sistema si el
    turno se recupera y responde con normalidad (``status == "ok"``) -- eso es el comportamiento
    correcto ante una entrada inválida, no una incidencia. Tampoco es un error real un issue de
    calidad de respuesta (p. ej. TOOL_NOT_SELECTED): esos siguen siendo solo visibles en el panel.
    """
    return record.status == "error"


def _compose(record: TraceRecord, *, recipient: str, sender: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"[mIA] Error en traza {record.trace_id}"
    message["From"] = sender
    message["To"] = recipient
    lines = [
        f"Trace ID: {record.trace_id}",
        f"Estado: {record.status}",
        f"Iniciada: {record.started_at.isoformat()}",
        f"Dominio: {record.domain or '-'}",
        f"Herramientas llamadas: {', '.join(record.tools_called) or '-'}",
        f"Errores de herramienta: {record.tool_errors}",
        f"Rondas LLM: {record.llm_rounds}",
        "",
        "Issues detectados:" if record.issues else "Sin issues adicionales registrados.",
    ]
    lines += [f"- [{issue.type}] {issue.message}" for issue in record.issues]
    message.set_content("\n".join(lines))
    return message


def _send(message: EmailMessage, smtp: SmtpSettings) -> None:
    with smtplib.SMTP(smtp.host, smtp.port, timeout=10) as client:
        if smtp.use_tls:
            client.starttls()
        if smtp.username:
            client.login(smtp.username, smtp.password.get_secret_value())
        client.send_message(message)


async def notify_on_error(
    record: TraceRecord, *, recipient: str, smtp: SmtpSettings, cooldown_seconds: int
) -> None:
    """Nunca lanza excepciones: un fallo al avisar no debe afectar a nada más."""
    global _last_sent_at  # noqa: PLW0603
    if not recipient or not smtp.configured or not _is_real_error(record):
        return
    now = time.monotonic()
    if now - _last_sent_at < cooldown_seconds:
        return
    _last_sent_at = now
    try:
        message = _compose(record, recipient=recipient, sender=smtp.from_address or smtp.username)
        await asyncio.to_thread(_send, message, smtp)
    except Exception:
        log.warning("diagnostics.alert_email_failed")
