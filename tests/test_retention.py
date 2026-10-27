"""Depuración por retención: ConversationRepository y AuditRepository.

Ninguno de los dos tenía test propio antes de este fichero (CLAUDE.md: "Añadir tests cuando el
comportamiento no está cubierto").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mia.api.services import Services
from mia.data import AuditEvent, ConversationSession, ConversationTurn
from mia.data.repositories import AuditRepository, ConversationRepository


@pytest.mark.asyncio
async def test_audit_purge_expired_deletes_only_old_events(services: Services) -> None:
    now = datetime.now(UTC)
    async with services.db.session() as db:
        old = AuditEvent(
            user_id="u1",
            action="tool:nominas_persona",
            resource="nominas",
            outcome="ok",
            request_id="r1",
            detail={"arguments": {"nombre": "Ana"}},
        )
        recent = AuditEvent(
            user_id="u1",
            action="tool:nominas_persona",
            resource="nominas",
            outcome="ok",
            request_id="r2",
            detail={"arguments": {"nombre": "Ana"}},
        )
        db.add_all([old, recent])
        await db.flush()
        old.created_at = now - timedelta(days=1096)
        recent.created_at = now - timedelta(days=1)
        await db.flush()

    async with services.db.session() as db:
        deleted = await AuditRepository.purge_expired(db, retention_days=1095, now=now)
    assert deleted == 1

    async with services.db.session() as db:
        remaining = list((await db.scalars(select(AuditEvent))).all())
    assert [e.request_id for e in remaining] == ["r2"]


@pytest.mark.asyncio
async def test_audit_purge_expired_noop_when_nothing_vencido(services: Services) -> None:
    async with services.db.session() as db:
        deleted = await AuditRepository.purge_expired(db, retention_days=1095)
    assert deleted == 0


@pytest.mark.asyncio
async def test_conversation_purge_expired_deletes_old_sessions_and_turns(services: Services) -> None:
    now = datetime.now(UTC)
    async with services.db.session() as db:
        repo = ConversationRepository(db)
        old_session = await repo.get_or_create(None, "u1")
        await repo.add_turn(session_id=old_session.id, request_id="r1", role="user", content="hola")
        recent_session = await repo.get_or_create(None, "u2")
        await repo.add_turn(session_id=recent_session.id, request_id="r2", role="user", content="hola")
        await db.flush()
        old_session.updated_at = now - timedelta(days=31)
        await db.flush()

    async with services.db.session() as db:
        deleted = await ConversationRepository.purge_expired(db, retention_days=30, now=now)
    assert deleted > 0

    async with services.db.session() as db:
        sessions = list((await db.scalars(select(ConversationSession))).all())
        turns = list((await db.scalars(select(ConversationTurn))).all())
    assert [s.user_id for s in sessions] == ["u2"]
    assert len(turns) == 1
    assert turns[0].session_id == recent_session.id
