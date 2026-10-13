"""Búsqueda semántica sobre documentos sensibles indexados (nóminas, documentos firmados) —
índice HNSW de pgvector sobre ``hr_document_chunks.embedding``.

Mismo patrón que ``curriculums/search.py`` (``CvSearchIndex``): la búsqueda se resuelve en Postgres,
nunca cargando los fragmentos de un dominio completo en memoria. Cada instancia filtra por su propio
``domain``, porque ``sp_id`` (``document_id``) no es único entre bibliotecas de SharePoint distintas.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import HrDocumentChunk


@dataclass(frozen=True, slots=True)
class DocumentHit:
    document_id: int
    person_key: str | None
    score: float
    evidence: str


class DocumentSearchIndex:
    def __init__(self, domain: str) -> None:
        self._domain = domain

    async def search(
        self, db: AsyncSession, query_vector: list[float], *, allowed: set[int] | None, limit: int
    ) -> list[DocumentHit]:
        """``allowed``: ``document_id`` (``sp_id``) permitidos tras el filtro de metadatos; None = sin filtro."""
        distance = HrDocumentChunk.embedding.cosine_distance(query_vector)
        inner = (
            select(
                HrDocumentChunk.document_id,
                HrDocumentChunk.person_key,
                HrDocumentChunk.text,
                distance.label("distance"),
            )
            .where(HrDocumentChunk.domain == self._domain, HrDocumentChunk.embedding.is_not(None))
            .ext(distinct_on(HrDocumentChunk.document_id))
            .order_by(HrDocumentChunk.document_id, distance)
        )
        if allowed is not None:
            inner = inner.where(HrDocumentChunk.document_id.in_(allowed))
        subq = inner.subquery()
        stmt = (
            select(subq.c.document_id, subq.c.person_key, subq.c.text, subq.c.distance)
            .order_by(subq.c.distance)
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [DocumentHit(r.document_id, r.person_key, round(1 - r.distance, 3), r.text[:400]) for r in rows]
