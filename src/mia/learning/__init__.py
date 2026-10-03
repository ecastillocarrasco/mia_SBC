"""Motor de aprendizaje propio — vacío por ahora.

Valoraciones de respuestas, casos que fallaron y banco de evaluación, para mejorar el prompt
y las herramientas a partir de feedback real. Esto NO es fine-tuning del LLM: es trazabilidad
y mejora continua, en la misma línea que ``tools/eval_conversation.py`` hace hoy de forma
manual con un corpus fijo — aquí se trataría de capturar también el feedback que llega en vivo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ConversationFeedback:
    """Una valoración de una respuesta real, de quien la recibió o de una revisión manual."""

    turn_id: str
    helpful: bool
    comment: str | None
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """Un caso del banco de evaluación: una pregunta con su respuesta esperada (o su patrón),
    para poder repetir ``tools/eval_conversation.py`` sobre un corpus que crece con el tiempo."""

    question: str
    expected: str
    source: str
    """De dónde vino el caso: «modo sombra», «feedback de usuario», «regresión detectada»…"""


class FeedbackStore(ABC):
    """Contrato para guardar y consultar feedback y casos de evaluación.

    Sin implementación todavía: falta decidir dónde vive (misma base de datos de mIA o un
    almacén aparte) y qué retención aplica a los comentarios textuales.
    """

    @abstractmethod
    async def record(self, feedback: ConversationFeedback) -> None:
        raise NotImplementedError

    @abstractmethod
    async def failing_cases(self, *, limit: int = 50) -> list[EvaluationCase]:
        """Casos marcados como fallidos, para priorizar qué corregir primero."""
        raise NotImplementedError
