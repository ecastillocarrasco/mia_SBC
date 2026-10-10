"""Redacción de secretos y datos sensibles en trazas diagnósticas."""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = re.compile(
    r"(api[_\-]?key|password|passwd|secret|token|authorization|bearer|credential|"
    r"cert|pfx|private[_\-]?key|connection[_\-]?string|access[_\-]?key|"
    r"client[_\-]?secret|refresh[_\-]?token|session[_\-]?cookie)",
    re.IGNORECASE,
)

_PII_KEYS = re.compile(
    r"(email|mail|nombre|name|apellido|surname|telefono|phone|dni|nif|nie|"
    r"empleado_id|employee_id|user_id|oid|sub)",
    re.IGNORECASE,
)

_REDACTED = "***REDACTED***"
_PII_MASK = "***"


def redact(data: Any, *, mask_pii: bool = False) -> Any:
    """Redacta recursivamente secretos (siempre) y PII (si mask_pii=True)."""
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for k, v in data.items():
            key_str = str(k)
            if _SECRET_KEYS.search(key_str):
                result[k] = _REDACTED
            elif mask_pii and _PII_KEYS.search(key_str):
                result[k] = _PII_MASK
            else:
                result[k] = redact(v, mask_pii=mask_pii)
        return result
    if isinstance(data, list):
        return [redact(item, mask_pii=mask_pii) for item in data]
    if isinstance(data, str) and len(data) > 2000:
        # Trunca strings muy largos (prompts, respuestas raw) para no saturar memoria
        return data[:2000] + "…[truncado]"
    return data


def safe_str(value: Any, max_chars: int = 500) -> str:
    """Convierte a string de forma segura truncando si es necesario."""
    s = str(value)
    if len(s) > max_chars:
        return s[:max_chars] + "…"
    return s
