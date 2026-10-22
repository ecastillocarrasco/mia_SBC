"""Read-only progress report of CV and sensitive-document vector indexing.

Run from the mIA project root, with the same .env as the backend:
    python tools/mia_index_status.py
    python tools/mia_index_status.py --json

Prints counts only. Never prints personal content or credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import and_, func, select

from mia.data import (
    CvChunk,
    CvDocument,
    CvText,
    Database,
    HrDocumentChunk,
    HrDocumentText,
    Payslip,
    SignedDocument,
    SourceSyncState,
)
from mia.settings import get_settings


async def _scalar(session, stmt):
    return int((await session.scalar(stmt)) or 0)


async def _cv_status(session):
    total = await _scalar(session, select(func.count()).select_from(CvDocument))
    counts = dict((str(status), int(count)) for status, count in (
        await session.execute(select(CvText.status, func.count()).group_by(CvText.status))
    ).all())
    indexed_with_vectors = await _scalar(
        session,
        select(func.count(func.distinct(CvChunk.document_id))).select_from(CvChunk),
    )
    stale = await _scalar(
        session,
        select(func.count()).select_from(CvDocument).join(
            CvText, CvText.document_id == CvDocument.sp_id, isouter=True
        ).where(
            (CvText.document_id.is_(None))
            | CvText.source_modified.is_distinct_from(CvDocument.modified_at)
        ),
    )
    return {
        "source": "cv_docs", "total_metadata": total,
        "with_vectors": indexed_with_vectors,
        "pending_new_or_modified": stale,
        "statuses": counts,
        "non_ok": max(0, total - counts.get("ok", 0)),
    }


async def _document_status(session, domain, model):
    total = await _scalar(session, select(func.count()).select_from(model))
    counts = dict((str(status), int(count)) for status, count in (
        await session.execute(
            select(HrDocumentText.status, func.count())
            .where(HrDocumentText.domain == domain).group_by(HrDocumentText.status)
        )
    ).all())
    indexed_with_vectors = await _scalar(
        session,
        select(func.count(func.distinct(HrDocumentChunk.document_id)))
        .where(HrDocumentChunk.domain == domain),
    )
    stale = await _scalar(
        session,
        select(func.count()).select_from(model).join(
            HrDocumentText,
            and_(HrDocumentText.domain == domain, HrDocumentText.document_id == model.sp_id),
            isouter=True,
        ).where(
            HrDocumentText.document_id.is_(None)
            | HrDocumentText.source_modified.is_distinct_from(model.modified_at)
        ),
    )
    return {
        "source": domain, "total_metadata": total,
        "with_vectors": indexed_with_vectors,
        "pending_new_or_modified": stale,
        "statuses": counts,
        "non_ok": max(0, total - counts.get("ok", 0)),
    }


async def collect():
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session() as session:
            states = {}
            for state in (await session.scalars(
                select(SourceSyncState).where(SourceSyncState.source.in_([
                    "curriculums", "cv_docs", "nominas", "documentos_firmados"
                ]))
            )).all():
                states[state.source] = {
                    "status": state.status,
                    "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
                    "item_count": state.item_count,
                    "last_error": bool(state.last_error),
                }
            data = {
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "storage": "PostgreSQL + pgvector",
                "sensitive_indexing_enabled": settings.data.index_sensitive_content,
                "sync_sources": states,
                "indexes": [
                    await _cv_status(session),
                    await _document_status(session, "nominas", Payslip),
                    await _document_status(session, "documentos_firmados", SignedDocument),
                ],
            }
            return data
    finally:
        await db.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = asyncio.run(collect())
    except Exception as exc:
        print(f"ERROR: No se ha podido consultar la base de datos: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
        return
    print("mIA | Estado de indexacion |", data["checked_at_utc"])
    print("Repositorio:", data["storage"])
    print("Indexacion sensible:", "activada" if data["sensitive_indexing_enabled"] else "DESACTIVADA")
    for row in data["indexes"]:
        print(
            f"{row['source']:20} metadatos={row['total_metadata']:7} "
            f"con_vectores={row['with_vectors']:7} "
            f"nuevos_o_modificados={row['pending_new_or_modified']:7} "
            f"no_ok={row['non_ok']:7} estados={row['statuses']}"
        )
    for source, state in data["sync_sources"].items():
        print(f"fuente {source:20} estado={state['status']} ultimo_ok={state['last_success_at']}")
    print("NOTA: 'no_ok' incluye archivos vacios, demasiado grandes o fallidos; revisar sus estados.")


if __name__ == "__main__":
    main()
