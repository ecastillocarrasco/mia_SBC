"""Extractive mailbox summaries rendered locally for the authenticated owner."""

from __future__ import annotations

import re
from typing import Any

from mia.conversation.tools import ToolContext
from mia.text import normalize_key

_COUNTS = dict(
    zip(("uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"), range(1, 11), strict=True)
)
_REQUEST = re.compile(
    r"(?:por favor,?\s+)?(?:puedes\s+)?"
    r"(?:resume(?:me)?|resumirme|hazme un resumen de|hacerme un resumen de|dame un resumen de)\s+"
    r"(?:mis|los)\s+(?:ultimos\s+)?(?P<count>\d+|" + "|".join(_COUNTS) + r")\s+"
    r"(?:correos|emails)(?:\s+recibidos)?(?:,?\s+por favor)?"
)


def direct_summary_arguments(ctx: ToolContext) -> dict[str, Any] | None:
    """Only standalone read requests; compound tasks remain with the planner."""
    match = _REQUEST.fullmatch(normalize_key(ctx.user_message).strip(" ¿?!."))
    if match is None:
        return None
    value = match["count"]
    count = int(value) if value.isdigit() else _COUNTS[value]
    return {"limite": count} if 1 <= count <= 10 else None


def local_summary(items: list[dict[str, Any]], bodies: list[str]) -> str:
    """Quote bounded source extracts; never infer actions or causes from a message."""
    if not items:
        return "No hay correos recibidos disponibles para resumir en tu buzón."
    paragraphs = [f"Resumen de tus {len(items)} correos más recientes:"]
    for item, body in zip(items, bodies, strict=True):
        text = re.sub(r"https?://\S+", "[enlace disponible en el correo]", body or item.get("extracto") or "")
        text = re.sub(r"\s+", " ", text).strip()
        sentences = re.split(r"(?<=[.!?])\s+", text)
        extract = " ".join(sentences[:2])[:500].strip()
        if len(text) > len(extract):
            extract += "…"
        if not extract:
            extract = "No hay texto legible disponible; abre el mensaje para revisar su contenido."
        paragraphs.append(
            f"**{item['ref']} · {item.get('asunto') or 'Sin asunto'}**\n"
            f"De: {item.get('de') or 'Remitente no indicado'}\nExtracto: {extract}"
        )
    return "\n\n".join(paragraphs)
