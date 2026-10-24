"""Formatos de presentaciones y mensajes del dominio de correo."""

from __future__ import annotations

import re
from typing import Any

from mia.modules.correo.tools import is_noreply

_SENDER = re.compile(r"^\s*(?P<name>.*?)\s*<(?P<address>[^>]+)>\s*$")


def sender_parts(value: Any) -> tuple[str, str]:
    match = _SENDER.match(str(value or ""))
    return (match["name"] or match["address"], match["address"]) if match else (str(value or ""), "")


def mail_message_view(payload: dict[str, Any]) -> dict[str, Any]:
    name, address = sender_parts(payload.get("de"))
    return {
        "ref": payload.get("ref"),
        "from_name": name,
        "from_address": address,
        "to": payload.get("para") or [],
        "subject": payload.get("asunto"),
        "received_at": payload.get("recibido"),
        "text": payload.get("texto"),
        "attachments": payload.get("adjuntos") or [],
        "no_reply": is_noreply(str(payload.get("de") or "")),
    }
