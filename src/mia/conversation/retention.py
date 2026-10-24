"""Depuración periódica de conversaciones vencidas en la base de datos operativa."""

from __future__ import annotations

import asyncio

from mia.data import Database
from mia.data.repositories import ConversationRepository
from mia.observability import get_logger

log = get_logger(__name__)


async def run_retention_cleanup(db: Database, retention_days: int, *, interval_seconds: int = 6 * 60 * 60) -> None:
    """Elimina sesiones inactivas y sus turnos cada seis horas en todas las réplicas."""
    while True:
        try:
            async with db.session() as session:
                deleted = await ConversationRepository.purge_expired(session, retention_days)
            if deleted:
                log.info("conversation.retention_purged", deleted_rows=deleted, retention_days=retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("conversation.retention_cleanup_failed")
        await asyncio.sleep(interval_seconds)
