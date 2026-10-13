"""Búsqueda semántica de CVs — índice HNSW de pgvector sobre ``hr_cv_chunks.embedding``.

Antes de la migración a pgvector esto cargaba todos los fragmentos en memoria (viable con ≈1.400
CVs). Con el volumen real actual (nóminas y documentos firmados comparten la misma infraestructura
de indexación y ya superan los 100.000 fragmentos entre los tres dominios), la búsqueda se empuja a
Postgres: nunca se trae a memoria más que los resultados ya filtrados.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import CvChunk


@dataclass(frozen=True, slots=True)
class Hit:
    candidate_id: int
    score: float
    evidence: str


def _best_per_candidate_query(query_vector: list[float], candidate_ids: set[int] | None):
    """``DISTINCT ON (candidate_id)``: el fragmento más parecido de cada candidatura, ordenado por
    distancia coseno — equivalente SQL de "mejor fragmento por candidato", calculado por el índice
    HNSW en vez de en memoria."""
    distance = CvChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(CvChunk.candidate_id, CvChunk.text, distance.label("distance"))
        .where(CvChunk.embedding.is_not(None), CvChunk.candidate_id.is_not(None))
        .ext(distinct_on(CvChunk.candidate_id))
        .order_by(CvChunk.candidate_id, distance)
    )
    if candidate_ids is not None:
        stmt = stmt.where(CvChunk.candidate_id.in_(candidate_ids))
    return stmt


class CvSearchIndex:
    async def search(
        self, db: AsyncSession, query_vector: list[float], *, allowed: set[int] | None, limit: int
    ) -> list[Hit]:
        inner = _best_per_candidate_query(query_vector, allowed).subquery()
        stmt = select(inner.c.candidate_id, inner.c.text, inner.c.distance).order_by(inner.c.distance).limit(limit)
        rows = (await db.execute(stmt)).all()
        return [Hit(r.candidate_id, round(1 - r.distance, 3), r.text[:400]) for r in rows]

    async def best_per_candidate(
        self, db: AsyncSession, query_vector: list[float], candidates: set[int]
    ) -> dict[int, tuple[float, str]]:
        """Para cada candidato, su fragmento de CV más parecido a la consulta: {id: (similitud, texto)}."""
        if not candidates:
            return {}
        rows = (await db.execute(_best_per_candidate_query(query_vector, candidates))).all()
        return {r.candidate_id: (1 - r.distance, r.text) for r in rows}
