"""Conocimiento documental de la empresa (RAG) — vacío por ahora, preparado para Azure AI Search.

Cuando se implemente: indexar documentos no estructurados (políticas, manuales, procedimientos,
convenios) en Azure AI Search, y exponer una búsqueda semántica que ``conversation/`` pueda
ofrecer como una herramienta más -con su propio ``Permission``-, igual que hoy
``modules/rrhh/curriculums/search.py`` hace con los CV. No se acopla a ningún módulo de negocio
concreto: cualquier módulo (RRHH, y después Finanzas, Legal…) podrá apoyarse en el mismo índice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """Un fragmento de documento recuperado, con su fuente para poder citarla en la respuesta."""

    title: str
    content: str
    source_url: str | None = None
    score: float = 0.0


class KnowledgeIndex(ABC):
    """Contrato para un índice de conocimiento documental (Azure AI Search u otro).

    Sin implementación todavía: falta decidir qué documentos se indexan primero y con qué
    permiso se protege cada colección.
    """

    @abstractmethod
    async def search(self, query: str, *, top: int = 5) -> list[KnowledgeDocument]:
        """Los fragmentos más relevantes para ``query``, ya listos para citar en la respuesta."""
        raise NotImplementedError
