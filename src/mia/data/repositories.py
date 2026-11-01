"""Acceso a datos operativos."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data.models import AuditEvent, ConversationSession, ConversationTurn, MemoryPreference, UserMemory
from mia.text import normalize_key


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
        return int(cast(CursorResult[Any], turns_result).rowcount or 0) + int(
            cast(CursorResult[Any], sessions_result).rowcount or 0
        )


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
        return int(cast(CursorResult[Any], result).rowcount or 0)


class MemoryLimitReachedError(Exception):
    """El usuario ya tiene el máximo de recuerdos permitido en esta versión de la Memoria Inteligente."""


class MemoryRepository:
    """Recuerdos manuales por usuario (Memoria Inteligente V1).

    Aislamiento entre usuarios: toda consulta/escritura filtra siempre por ``user_id`` explícito,
    nunca por un ID de recuerdo a secas — ``delete_memory`` trata un recuerdo ajeno igual que uno
    inexistente, para no confirmar ni desmentir su existencia a quien no es su propietario. Vive
    en la capa de datos (junto a ``ConversationRepository``) y no en ``mia.modules.memoria``
    porque el propio motor de conversación la usa directamente para la recuperación pasiva entre
    turnos (``mia.conversation.engine``); las herramientas que el LLM puede invocar sí viven en
    ``mia.modules.memoria.tools``, igual que el resto de dominios.
    """

    def __init__(self, db: AsyncSession, *, max_items_per_user: int = 50) -> None:
        self._db = db
        self._max_items_per_user = max_items_per_user

    async def is_enabled(self, user_id: str) -> bool:
        pref = await self._db.get(MemoryPreference, user_id)
        return bool(pref and pref.enabled)

    async def set_enabled(self, user_id: str, enabled: bool) -> None:
        pref = await self._db.get(MemoryPreference, user_id)
        if pref is None:
            self._db.add(MemoryPreference(user_id=user_id, enabled=enabled))
        else:
            pref.enabled = enabled

    async def list_memories(self, user_id: str) -> list[UserMemory]:
        stmt = select(UserMemory).where(UserMemory.user_id == user_id).order_by(UserMemory.created_at.desc())
        return list((await self._db.scalars(stmt)).all())

    async def add_memory(self, user_id: str, content: str) -> UserMemory:
        existing = await self.list_memories(user_id)
        if len(existing) >= self._max_items_per_user:
            raise MemoryLimitReachedError(user_id)
        memory = UserMemory(user_id=user_id, content=content)
        self._db.add(memory)
        await self._db.flush()
        return memory

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        memory = await self._db.get(UserMemory, memory_id)
        if memory is None or memory.user_id != user_id:
            return False
        await self._db.delete(memory)
        return True

    async def delete_matching(self, user_id: str, text: str) -> list[UserMemory]:
        """Borra los recuerdos del usuario cuyo texto contiene ``text`` (sin tildes ni mayúsculas,
        como el resto de búsquedas de mIA) y devuelve los borrados — pensado para borrar por
        lenguaje natural, sin que quien pide el borrado necesite conocer un ID interno."""
        needle = normalize_key(text)
        matches = [m for m in await self.list_memories(user_id) if needle in normalize_key(m.content)]
        for memory in matches:
            await self._db.delete(memory)
        return matches

    async def delete_all(self, user_id: str) -> int:
        result = await self._db.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
        return int(cast(CursorResult[Any], result).rowcount or 0)
