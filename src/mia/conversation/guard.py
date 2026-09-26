"""Salvaguarda determinista sobre lo que dice mIA.

Hay compromisos que mIA no puede cumplir (avisar más tarde, hacer seguimiento,
volver a escribir). El prompt ya lo prohíbe, pero el modelo a veces lo dice
igualmente, así que las frases que los contienen se eliminan en código antes
de mostrarlas o locutarlas.
"""

from __future__ import annotations

import re

from mia.observability import get_logger

log = get_logger(__name__)

_PROMISES = re.compile(
    r"\b(?:"
    r"te\s+(?:lo\s+)?(?:avisar[ée]|notificar[ée]|informar[ée]|comunicar[ée]|recordar[ée]|escribir[ée])"
    r"|te\s+lo\s+har[ée]\s+saber|te\s+har[ée]\s+saber"
    r"|me\s+pondr[ée]\s+en\s+contacto"
    r"|volver[ée]\s+a\s+(?:escribirte|contactarte|avisarte)"
    r"|te\s+mantendr[ée]\s+informad[oa]"
    r")\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?…])\s+")


def is_blocked(sentence: str) -> bool:
    return bool(_PROMISES.search(sentence))


def clean(text: str) -> str:
    """Elimina las frases con compromisos imposibles; conserva el resto intacto."""
    if not _PROMISES.search(text):
        return text
    kept: list[str] = []
    for line in text.split("\n"):
        parts = [p for p in _SENTENCES.split(line) if not is_blocked(p)]
        kept.append(" ".join(parts))
    result = "\n".join(kept).strip()
    log.info("guard.removed_promise")
    return result
