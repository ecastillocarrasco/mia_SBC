"""mIA SBC: one-shot vector indexing of existing metadata; no sync/migration.

Read-only by default. --execute is required for writes. The script operates
on existing indexer per-document code, deliberately avoiding indexer.run() and
its global orphan cleanup; it never runs SyncRunner.

Requires the original mIA environment and dependencies. Run from project root:
  .venv\\Scripts\\python.exe tools\\mia_index_lote_controlado.py --domain nominas --limit 20
  .venv\\Scripts\\python.exe tools\\mia_index_lote_controlado.py --domain nominas --limit 20 --execute

This still modifies per-document vector and extracted text tables and may call
remote OCR / embedding providers configured by mIA. Do not run concurrently
with another synchronization or indexing process.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from sqlalchemy import and_, or_, select, text
from sqlalchemy.engine import make_url

from mia.data import CvDocument, CvText, Database, HrDocumentText, Payslip, SignedDocument
from mia.settings import get_settings

# Dedicated advisory lock: only blocks other runs of this script, not the
# existing mIA synchronized jobs. Verify those are idle separately.
_LOCK_NAMESPACE = 581047
_LOCK_KEY = 14026


def _candidate_query(domain: str):
    if domain == "cv_docs":
        return (
            select(CvDocument)
            .outerjoin(CvText, CvText.document_id == CvDocument.sp_id)
            .where(or_(
                CvText.document_id.is_(None),
                CvText.source_modified != CvDocument.modified_at,
                and_(CvText.status.in_(("empty", "unsupported")),
                     or_(CvText.detail.is_(None), CvText.detail.not_like("ocr%"))),
            ))
            .order_by(CvDocument.modified_at.desc())
        )
    model = Payslip if domain == "nominas" else SignedDocument
    return (
        select(model)
        .outerjoin(HrDocumentText, and_(
            HrDocumentText.domain == domain,
            HrDocumentText.document_id == model.sp_id,
        ))
        .where(or_(
            HrDocumentText.document_id.is_(None),
            HrDocumentText.source_modified != model.modified_at,
            and_(HrDocumentText.status.in_(("empty", "unsupported")),
                 or_(HrDocumentText.detail.is_(None), HrDocumentText.detail.not_like("ocr%"))),
        ))
        .order_by(model.modified_at.desc())
    )


async def _run(domain: str, limit: int, execute: bool) -> int:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (url.get_backend_name() != "postgresql" or url.database != "mia"
            or (url.host or "").lower() not in ("localhost", "127.0.0.1", "::1")
            or (url.port or 5432) != 5432):
        print("BLOQUEADO: la configuracion no apunta a PostgreSQL local /mia puerto 5432.")
        return 2
    if execute and domain != "cv_docs" and not settings.data.index_sensitive_content:
        print("BLOQUEADO: indexacion sensible desactivada en la configuracion.")
        return 2

    db = Database(settings.database_url)
    try:
        async with db.engine.connect() as guard:
            database_name = await guard.scalar(text("SELECT current_database()"))
            if database_name != "mia":
                print("BLOQUEADO: el servidor no esta usando la base 'mia'.")
                return 2
            acquired = await guard.scalar(
                text("SELECT pg_try_advisory_lock(:ns, :key)"),
                {"ns": _LOCK_NAMESPACE, "key": _LOCK_KEY},
            )
            if not acquired:
                print("BLOQUEADO: existe otra ejecucion de este indexador controlado.")
                return 2
            try:
                query = _candidate_query(domain).limit(limit)
                async with db.session() as session:
                    candidates = list((await session.scalars(query)).all())
                print(f"Base verificada: {database_name} | Dominio: {domain} | Candidatos lote: {len(candidates)}")
                if not execute:
                    print("SIMULACION: no se descargaron documentos ni se escribieron vectores.")
                    return 0
                if not candidates:
                    print("No se encontraron candidatos elegibles para el lote.")
                    return 0
                # Imports/clients are instantiated only when writes are authorized.
                from mia.ingestion.sync.factory import build_sharepoint_client
                from mia.llm import build_llm_provider
                from mia.modules.rrhh.curriculums.indexer import CvIndexer
                from mia.modules.rrhh.document_indexing import DocumentIndexer
                client = build_sharepoint_client(settings)
                llm = build_llm_provider(settings.llm, settings.privacy_gateway)
                try:
                    common = dict(
                        db=db, client=client, llm=llm,
                        embedding_model=settings.curriculums.embedding_model,
                        batch=limit,
                        max_bytes=settings.curriculums.max_file_mb * 1024 * 1024,
                    )
                    if domain == "cv_docs":
                        indexer = CvIndexer(**common)
                    else:
                        model, title = ((Payslip, "Nominas") if domain == "nominas"
                                        else (SignedDocument, "DocumentosFirmadosV2"))
                        indexer = DocumentIndexer(domain=domain, list_title=title,
                                                  model=model, **common)
                    results = Counter()
                    for i, document in enumerate(candidates, 1):
                        try:
                            status = await indexer._index_one(document)
                        except Exception as exc:
                            status = "exception"
                            print(f"ERROR en elemento {i}/{len(candidates)}: {type(exc).__name__}")
                        results[status] += 1
                        print(f"{i}/{len(candidates)} procesado; estado={status}", flush=True)
                    print("RESUMEN:", dict(results))
                    return 0 if not (results.get("exception") or results.get("error")) else 1
                finally:
                    await llm.aclose()
                    await client.aclose()
            finally:
                # Release on the same connection before it returns to the pool.
                await guard.execute(
                    text("SELECT pg_advisory_unlock(:ns, :key)"),
                    {"ns": _LOCK_NAMESPACE, "key": _LOCK_KEY},
                )
    finally:
        await db.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True,
                        choices=["cv_docs", "nominas", "documentos_firmados"])
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--execute", action="store_true",
                        help="procesa de verdad el lote; por defecto solo diagnostica")
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit debe ser entre 1 y 20 para la fase de validacion")
    raise SystemExit(asyncio.run(_run(args.domain, args.limit, args.execute)))


if __name__ == "__main__":
    main()
