"""Indexación de CVs: descarga, extracción de texto, fragmentos y embeddings.

Se ejecuta tras la sincronización. Solo procesa CVs nuevos o modificados (por
lotes), así que el coste de embeddings se paga una vez por CV.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, delete, or_, select

from mia.connectors.sharepoint import SharePointClient, SharePointError
from mia.data import CvChunk, CvDocument, CvText, Database
from mia.llm import LLMProvider
from mia.modules.rrhh.document_indexing import (
    OCR_INSTRUCTION,  # compatibilidad: importaciones anteriores desde curriculums.indexer
    OCR_MAX_PAGES,
    LocalOCRError,
    chunk_text,
    clean_text,
    extract_document_text_local,
    extract_text,
    image_media_type,
    normalize,
    render_pdf_pages,  # lo usa el modulo de adjuntos/vision
)
from mia.observability import get_logger

log = get_logger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # PDF mal formados: el estado ya lo refleja

EMBED_BATCH = 64


@dataclass(slots=True)
class IndexReport:
    processed: int = 0
    indexed: int = 0
    failed: int = 0
    removed: int = 0
    pending: int = 0
    statuses: dict[str, int] = field(default_factory=dict)


class CvIndexer:
    def __init__(
        self,
        *,
        db: Database,
        client: SharePointClient,
        llm: LLMProvider,
        embedding_model: str,
        batch: int = 200,
        max_bytes: int = 15 * 1024 * 1024,
    ) -> None:
        self._db = db
        self._client = client
        self._llm = llm
        self._model = embedding_model
        self._batch = batch
        self._max_bytes = max_bytes

    async def run(self, progress: Callable[[int, int], None] | None = None) -> IndexReport:
        report = IndexReport()
        async with self._db.session() as db:
            alive = select(CvDocument.sp_id)
            removed = await db.execute(delete(CvText).where(CvText.document_id.not_in(alive)))
            await db.execute(delete(CvChunk).where(CvChunk.document_id.not_in(alive)))
            report.removed = int(getattr(removed, "rowcount", 0) or 0)
            stale = (
                select(CvDocument)
                .outerjoin(CvText, CvText.document_id == CvDocument.sp_id)
                .where(
                    or_(
                        CvText.document_id.is_(None),
                        CvText.source_modified != CvDocument.modified_at,
                        # Escaneados o imágenes que aún no han pasado por la lectura visual.
                        and_(
                            CvText.status.in_(("empty", "unsupported")),
                            or_(CvText.detail.is_(None), CvText.detail.not_like("ocr%")),
                        ),
                    )
                )
                .order_by(CvDocument.modified_at.desc())
            )
            pending = list((await db.scalars(stale)).all())
        report.pending = max(0, len(pending) - self._batch)
        for document in pending[: self._batch]:
            status = await self._index_one(document)
            report.processed += 1
            report.statuses[status] = report.statuses.get(status, 0) + 1
            report.indexed += status == "ok"
            report.failed += status == "error"
            if progress and (report.processed % 25 == 0 or report.processed == min(len(pending), self._batch)):
                progress(report.processed, min(len(pending), self._batch))
        log.info(
            "cv_index.finished",
            processed=report.processed,
            indexed=report.indexed,
            failed=report.failed,
            removed=report.removed,
            pending=report.pending,
        )
        return report

    async def _index_one(self, document: CvDocument) -> str:
        detail = None
        text = ""
        try:
            content = await self._client.download(document.file_ref, self._max_bytes)
            status, text, detail = await asyncio.to_thread(
                extract_document_text_local, content, document.file_name
            )
        except LocalOCRError as exc:
            # Fail closed y conserva cualquier indice previo.
            log.warning("cv_index.local_ocr_failed", document=document.sp_id, reason=str(exc))
            return "error"
        except SharePointError as exc:
            status, detail = ("too_large" if "demasiado grande" in str(exc) else "error"), str(exc)[:300]
        except Exception as exc:  # PDF o DOCX corrupto
            status, detail = "error", f"{type(exc).__name__}: {exc}"[:300]
        chunks = chunk_text(text) if status == "ok" else []
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(chunks), EMBED_BATCH):
                vectors.extend(await self._llm.embed(chunks[start : start + EMBED_BATCH], self._model))
        except Exception as exc:
            log.warning("cv_index.embed_failed", document=document.sp_id, error=str(exc))
            return "error"  # se reintentará en la siguiente ejecución (no se guarda el texto)
        try:
            await self._persist(document, status=status, text=text, detail=detail, chunks=chunks, vectors=vectors)
        except Exception as exc:  # un CV problemático nunca detiene la indexación del resto
            log.warning("cv_index.persist_failed", document=document.sp_id, error=str(exc)[:300])
            await self._persist(document, status="error", text="", detail=type(exc).__name__, chunks=[], vectors=[])
            return "error"
        return status

    async def _persist(
        self,
        document: CvDocument,
        *,
        status: str,
        text: str,
        detail: str | None,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> None:
        async with self._db.session() as db:
            await db.execute(delete(CvChunk).where(CvChunk.document_id == document.sp_id))
            await db.execute(delete(CvText).where(CvText.document_id == document.sp_id))
            db.add(
                CvText(
                    document_id=document.sp_id,
                    candidate_id=document.candidate_id,
                    source_modified=document.modified_at,
                    status=status,
                    text=text or None,
                    detail=detail,
                    extracted_at=datetime.now(UTC),
                )
            )
            db.add_all(
                CvChunk(
                    document_id=document.sp_id,
                    candidate_id=document.candidate_id,
                    position=i,
                    text=chunk,
                    embedding=normalize(vector),
                )
                for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
            )
