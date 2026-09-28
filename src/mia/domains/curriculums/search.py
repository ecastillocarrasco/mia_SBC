"""Búsqueda semántica de CVs en memoria (≈1.400 CVs: milisegundos, sin extensiones de base de datos).

El índice se recarga solo cuando cambian los fragmentos. Cuando el volumen lo pida
se sustituye por pgvector sin tocar las herramientas.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import CvChunk
from mia.domains.curriculums.indexer import pack


@dataclass(frozen=True, slots=True)
class Hit:
    candidate_id: int
    score: float
    evidence: str


class CvSearchIndex:
    def __init__(self) -> None:
        self._signature: tuple[int, int] | None = None
        self._matrix = np.zeros((0, 1), dtype=np.float32)
        self._candidates: list[int] = []
        self._texts: list[str] = []
        self._lock = asyncio.Lock()

    async def _ensure(self, db: AsyncSession) -> None:
        count, last = (await db.execute(select(func.count(CvChunk.id), func.max(CvChunk.id)))).one()
        signature = (int(count or 0), int(last or 0))
        if signature == self._signature:
            return
        async with self._lock:
            rows = (
                await db.execute(
                    select(CvChunk.candidate_id, CvChunk.text, CvChunk.embedding).where(
                        CvChunk.embedding.is_not(None), CvChunk.candidate_id.is_not(None)
                    )
                )
            ).all()
            vectors = [np.frombuffer(r.embedding, dtype=np.float32) for r in rows]
            self._matrix = np.vstack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32)
            self._candidates = [int(r.candidate_id) for r in rows]
            self._texts = [str(r.text) for r in rows]
            self._signature = signature

    async def search(
        self, db: AsyncSession, query_vector: list[float], *, allowed: set[int] | None, limit: int
    ) -> list[Hit]:
        await self._ensure(db)
        if not self._candidates:
            return []
        query = np.frombuffer(pack(query_vector), dtype=np.float32)
        if query.shape[0] != self._matrix.shape[1]:
            return []
        scores = self._matrix @ query
        best: dict[int, tuple[float, int]] = {}
        for row in np.argsort(-scores):
            candidate = self._candidates[row]
            if allowed is not None and candidate not in allowed:
                continue
            if candidate not in best:
                best[candidate] = (float(scores[row]), int(row))
                if len(best) >= limit:
                    break
        return [Hit(c, round(s, 3), self._texts[i][:400]) for c, (s, i) in best.items()]

    async def best_per_candidate(
        self, db: AsyncSession, query_vector: list[float], candidates: set[int]
    ) -> dict[int, tuple[float, str]]:
        """Para cada candidato, su fragmento de CV más parecido a la consulta: {id: (similitud, texto)}."""
        await self._ensure(db)
        if not self._candidates or not candidates:
            return {}
        query = np.frombuffer(pack(query_vector), dtype=np.float32)
        if query.shape[0] != self._matrix.shape[1]:
            return {}
        scores = self._matrix @ query
        best: dict[int, tuple[float, str]] = {}
        for row, candidate in enumerate(self._candidates):
            if candidate in candidates and (candidate not in best or scores[row] > best[candidate][0]):
                best[candidate] = (float(scores[row]), self._texts[row])
        return best
