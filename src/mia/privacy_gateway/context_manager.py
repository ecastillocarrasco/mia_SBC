"""Identidad de la operación en curso (usuario + id de turno), disponible para el gateway en el punto
exacto donde se llama a ``LLMProvider.stream()`` — sin que el contrato ``LLMRequest`` tenga que llevar
esa información, y sin depender de que el sistema de diagnóstico (opcional) esté activado.

Es deliberadamente independiente de ``mia.diagnostics``: la protección de privacidad no puede depender
de una función de observabilidad que se puede desactivar.

Se fija con un ``set`` simple, no con un gestor de contexto: cada turno (``ConversationEngine.run``) es
el punto de entrada único y vuelve a fijarlo al principio, así que no hace falta "deshacerlo" al salir
— cada tarea asyncio tiene su propia copia de los ContextVar (no se filtra entre peticiones concurrentes),
y forzar un reset al cerrar un generador async es precisamente lo que causó el bug ya corregido en
``mia.diagnostics.trace`` (cierre del generador en un contexto distinto al que lo creó).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class OperationContext:
    user_id: str
    operation_id: str


_current: ContextVar[OperationContext | None] = ContextVar("_mia_privacy_operation", default=None)
EmbeddingPurpose = Literal["query", "minimized_source", "private_source"]
_embedding_purpose: ContextVar[EmbeddingPurpose | None] = ContextVar("_mia_embedding_purpose", default=None)


@contextmanager
def embedding_scope(purpose: EmbeddingPurpose) -> Iterator[None]:
    """Trusted caller declares payload origin; external embeddings fail closed by default."""
    token = _embedding_purpose.set(purpose)
    try:
        yield
    finally:
        _embedding_purpose.reset(token)


def current_embedding_purpose() -> EmbeddingPurpose | None:
    return _embedding_purpose.get()


def set_operation_context(*, user_id: str, operation_id: str) -> None:
    _current.set(OperationContext(user_id=user_id, operation_id=operation_id))


def current_operation() -> OperationContext | None:
    return _current.get()
