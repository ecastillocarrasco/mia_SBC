"""Búsqueda semántica en memoria sobre documentos sensibles indexados (nóminas, documentos firmados).

Mismo patrón que ``CvSearchIndex`` (``curriculums/search.py``): el índice se recarga solo cuando
cambian los fragmentos del dominio, y ``allowed`` filtra por los ``document_id`` (``sp_id`` de
``Payslip``/``SignedDocument``) que ya han pasado el filtro de metadatos (persona, periodo,
departamento…), igual que ``CvSearchIndex`` filtra por ``candidate_id``. Cada instancia indexa un
solo ``domain``, porque ``sp_id`` no es único entre bibliotecas distintas.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import HrDocumentChunk
from mia.modules.rrhh.document_indexing import pack


@dataclass(frozen=True, slots=True)
class DocumentHit:
    document_id: int
    person_key: str | None
    score: float
    evidence: str


class DocumentSearchIndex:
    def __init__(self, domain: str) -> None:
        self._domain = domain
        self._signature: tuple[int, int] | None = None
        self._matrix = np.zeros((0, 1), dtype=np.float32)
        self._document_ids: list[int] = []
        self._person_keys: list[str | None] = []
        self._texts: list[str] = []
        self._lock = asyncio.Lock()

    async def _ensure(self, db: AsyncSession) -> None:
        count, last = (
            await db.execute(
                select(func.count(HrDocumentChunk.id), func.max(HrDocumentChunk.id)).where(
                    HrDocumentChunk.domain == self._domain
                )
            )
        ).one()
        signature = (int(count or 0), int(last or 0))
        if signature == self._signature:
            return
        async with self._lock:
            rows = (
                await db.execute(
                    select(
                        HrDocumentChunk.document_id, HrDocumentChunk.person_key, HrDocumentChunk.text, HrDocumentChunk.embedding
                    ).where(HrDocumentChunk.domain == self._domain, HrDocumentChunk.embedding.is_not(None))
                )
            ).all()
            vectors = [np.frombuffer(r.embedding, dtype=np.float32) for r in rows]
            self._matrix = np.vstack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32)
            self._document_ids = [int(r.document_id) for r in rows]
            self._person_keys = [r.person_key for r in rows]
            self._texts = [str(r.text) for r in rows]
            self._signature = signature

    async def search(
        self, db: AsyncSession, query_vector: list[float], *, allowed: set[int] | None, limit: int
    ) -> list[DocumentHit]:
        """``allowed``: ``document_id`` (``sp_id``) permitidos tras el filtro de metadatos; None = sin filtro."""
        await self._ensure(db)
        if not self._document_ids:
            return []
        query = np.frombuffer(pack(query_vector), dtype=np.float32)
        if query.shape[0] != self._matrix.shape[1]:
            return []
        scores = self._matrix @ query
        best: dict[int, tuple[float, int]] = {}
        for row in np.argsort(-scores):
            document_id = self._document_ids[row]
            if allowed is not None and document_id not in allowed:
                continue
            if document_id not in best:
                best[document_id] = (float(scores[row]), int(row))
                if len(best) >= limit:
                    break
        return [
            DocumentHit(d, self._person_keys[i], round(s, 3), self._texts[i][:400]) for d, (s, i) in best.items()
        ]
