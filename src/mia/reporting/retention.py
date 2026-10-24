"""Elimina blobs y metadatos de informes cuando termina su periodo de descarga."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from mia.attachments.storage import StorageBackend
from mia.data import Database, Report
from mia.observability import get_logger

log = get_logger(__name__)


def _delete_legacy_file(path: Path, directory: Path) -> None:
    root = directory.resolve()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError("La ruta antigua del informe está fuera del directorio permitido")
    resolved.unlink(missing_ok=True)


async def run_report_cleanup(
    db: Database,
    storage: StorageBackend,
    local_directory: Path,
    *,
    interval_seconds: int = 6 * 60 * 60,
) -> None:
    while True:
        try:
            async with db.session() as session:
                stmt = select(Report).where(Report.expires_at <= datetime.now(UTC))
                expired = list((await session.scalars(stmt)).all())
                for report in expired:
                    try:
                        path = Path(report.path)
                        if path.is_absolute():  # compatibilidad con filas creadas antes del backend compartido
                            await asyncio.to_thread(_delete_legacy_file, path, local_directory)
                        else:
                            await storage.delete(report.path)
                    except Exception:
                        log.exception("reports.retention_blob_delete_failed", report_id=report.id)
                        continue
                    await session.execute(delete(Report).where(Report.id == report.id))
            if expired:
                log.info("reports.retention_purged", deleted_reports=len(expired))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reports.retention_cleanup_failed")
        await asyncio.sleep(interval_seconds)
