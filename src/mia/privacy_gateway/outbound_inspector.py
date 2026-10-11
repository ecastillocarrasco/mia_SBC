"""Última inspección antes de enviar texto al proveedor LLM: secretos técnicos.

Esto es independiente de Presidio (que detecta identificadores PERSONALES, no credenciales) y nunca
es reversible: un secreto se elimina, no se tokeniza — no tiene sentido "restaurar" una contraseña en
la respuesta del LLM, y hacerlo sería el propio riesgo que se quiere evitar.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # claves estilo OpenAI
    re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[=:]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"),  # JWT
    re.compile(r"(?i)(?:mongodb|postgres(?:ql)?|mysql|redis)://\S+"),  # cadenas de conexión
]

_REDACTED = "[SECRETO_REDACTADO]"


def redact_secrets(text: str) -> tuple[str, int]:
    """Devuelve (texto_sin_secretos, nº de coincidencias). Nunca intenta ser reversible."""
    if not text:
        return text, 0
    count = 0
    out = text
    for pattern in _SECRET_PATTERNS:
        out, n = pattern.subn(_REDACTED, out)
        count += n
    return out, count


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS) if text else False
