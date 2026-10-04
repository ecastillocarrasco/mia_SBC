"""Extracción incremental del campo "habla" mientras el modelo escribe el JSON.

Permite enviar cada frase a la voz en cuanto se completa, sin esperar a que
termine la respuesta. Así el primer audio llega en torno a un segundo.
"""

from __future__ import annotations

import json
import re

_FIELD = re.compile(r'"habla"\s*:\s*"((?:[^"\\]|\\.)*)("?)', re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _decode_partial(raw: str) -> str:
    # Un escape cortado a mitad (p. ej. "\u00" o "\") se deja para el siguiente fragmento.
    cut = re.search(r"\\(u[0-9a-fA-F]{0,3})?$", raw)
    if cut:
        raw = raw[: cut.start()]
    try:
        return str(json.loads(f'"{raw}"'))
    except json.JSONDecodeError:
        return ""


class SpeechExtractor:
    def __init__(self) -> None:
        self._buffer = ""
        self._emitted = 0
        self.closed = False

    def feed(self, delta: str) -> list[str]:
        """Añade texto del modelo y devuelve las frases nuevas ya completas."""
        if self.closed:
            return []
        self._buffer += delta
        match = _FIELD.search(self._buffer)
        if not match:
            return []
        text = _decode_partial(match.group(1))
        if match.group(2) == '"':
            self.closed = True
            return self._take(text, final=True)
        return self._take(text, final=False)

    def finish(self) -> list[str]:
        if self.closed:
            return []
        self.closed = True
        match = _FIELD.search(self._buffer)
        return self._take(_decode_partial(match.group(1)), final=True) if match else []

    def _take(self, text: str, *, final: bool) -> list[str]:
        pending = text[self._emitted :]
        if final:
            self._emitted = len(text)
            return [p.strip() for p in _SENTENCE_END.split(pending) if p.strip()]
        parts = _SENTENCE_END.split(pending)
        if len(parts) < 2:
            return []
        complete = parts[:-1]
        consumed = len(pending) - len(parts[-1])
        self._emitted += consumed
        return [p.strip() for p in complete if p.strip()]
