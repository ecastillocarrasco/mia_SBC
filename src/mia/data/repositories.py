"""Acceso a datos operativos."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data.models import AuditEvent, ConversationSession, ConversationTurn


class SessionNotOwnedError(Exception):
    """La sesión existe pero pertenece a otro usuario."""


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_or_create(self, session_id: str | None, user_id: str) -> ConversationSession:
        if session_id:
            existing = await self._db.get(ConversationSession, session_id)
            if existing is not None:
                if existing.user_id != user_id:
                    raise SessionNotOwnedError(session_id)
                return existing
        created = ConversationSession(user_id=user_id, state={})
        if session_id and len(session_id) <= 32 and session_id.isalnum():
            created.id = session_id
        self._db.add(created)
        await self._db.flush()
        return created

    async def recent_turns(self, session_id: str, limit: int) -> list[ConversationTurn]:
        stmt = (
            select(ConversationTurn)
            .where(ConversationTurn.session_id == session_id)
            .order_by(ConversationTurn.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._db.scalars(stmt)).all())
        rows.reverse()
        return rows

    async def add_turn(self, **values: Any) -> ConversationTurn:
        turn = ConversationTurn(**values)
        self._db.add(turn)
        await self._db.flush()
        return turn

    @staticmethod
    async def purge_expired(db: AsyncSession, retention_days: int, *, now: datetime | None = None) -> int:
        """Elimina sesiones y mensajes vencidos. El estado conversacional también puede contener PII."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        expired_sessions = select(ConversationSession.id).where(ConversationSession.updated_at < cutoff)
        turns_result = await db.execute(
            delete(ConversationTurn).where(ConversationTurn.session_id.in_(expired_sessions))
        )
        sessions_result = await db.execute(delete(ConversationSession).where(ConversationSession.updated_at < cutoff))
        return int(turns_result.rowcount or 0) + int(sessions_result.rowcount or 0)


class AuditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(
        self,
        *,
        user_id: str,
        action: str,
        resource: str,
        outcome: str,
        request_id: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._db.add(
            AuditEvent(
                user_id=user_id,
                action=action,
                resource=resource,
                outcome=outcome,
                request_id=request_id,
                detail=detail or {},
            )
        )

    @staticmethod
    async def purge_expired(db: AsyncSession, retention_days: int, *, now: datetime | None = None) -> int:
        """Elimina eventos de auditoría vencidos. ``detail`` puede contener PII (argumentos de herramientas)."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        result = await db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
        return int(result.rowcount or 0)
