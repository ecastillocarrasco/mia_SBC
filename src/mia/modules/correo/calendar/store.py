"""Transiciones atómicas antes de llamar al proveedor. Nunca reejecuta running/unknown."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, select, true, update
from sqlalchemy.orm import aliased

from mia.conversation import ToolContext
from mia.data import Database
from mia.data.calendar import CalendarOperation
from mia.data.repositories import AuditRepository
from mia.observability import get_logger

log = get_logger(__name__)


async def purge_operations(db: Database, retention_days: int) -> None:
    async with db.session() as session:
        await session.execute(
            delete(CalendarOperation).where(
                CalendarOperation.expires_at < datetime.now(UTC) - timedelta(days=retention_days),
            )
        )


async def run_retention_cleanup(db: Database, retention_days: int) -> None:
    """Misma retención que la conversación; solo se arranca con calendario activo."""
    while True:
        try:
            await purge_operations(db, retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("calendar.retention_cleanup_failed")
        await asyncio.sleep(6 * 60 * 60)


class OperationStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def propose(self, ctx: ToolContext, payload: dict[str, Any], ttl: int) -> CalendarOperation:
        scope = ctx.session_state.setdefault("calendar_session_key", uuid.uuid4().hex)
        operation = CalendarOperation(
            id=uuid.uuid4().hex,
            user_id=ctx.user.user_id,
            session_key=scope,
            provider=payload["provider"],
            request_id=ctx.request_id,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
            payload=payload,
            result={},
        )
        async with self.db.session() as session:
            session.add(operation)
            await AuditRepository(session).record(
                user_id=ctx.user.user_id,
                action="calendar:propose",
                resource="correo:calendario",
                outcome="pending",
                request_id=ctx.request_id,
                detail={"operation_id": operation.id, "provider": operation.provider, "action": payload["action"]},
            )
        return operation

    async def get(self, ctx: ToolContext, operation_id: str) -> CalendarOperation | None:
        async with self.db.session() as session:
            return (
                await session.execute(
                    select(CalendarOperation).where(
                        CalendarOperation.id == operation_id,
                        CalendarOperation.user_id == ctx.user.user_id,
                        CalendarOperation.session_key == ctx.session_state.get("calendar_session_key", ""),
                    )
                )
            ).scalar_one_or_none()

    async def pending(self, ctx: ToolContext) -> list[CalendarOperation]:
        async with self.db.session() as session:
            return list(
                await session.scalars(
                    select(CalendarOperation)
                    .where(
                        CalendarOperation.user_id == ctx.user.user_id,
                        CalendarOperation.session_key == ctx.session_state.get("calendar_session_key", ""),
                        CalendarOperation.status == "pending",
                        CalendarOperation.expires_at > datetime.now(UTC),
                    )
                    .order_by(CalendarOperation.expires_at, CalendarOperation.id)
                )
            )

    async def claim(self, ctx: ToolContext, operation_id: str, *, require_unique: bool = False) -> bool:
        other = aliased(CalendarOperation)
        no_other = ~exists().where(
            other.user_id == ctx.user.user_id,
            other.session_key == ctx.session_state.get("calendar_session_key", ""),
            other.status == "pending",
            other.expires_at > datetime.now(UTC),
            other.id != operation_id,
        )
        async with self.db.session() as session:
            result = await session.execute(
                update(CalendarOperation)
                .where(
                    CalendarOperation.id == operation_id,
                    CalendarOperation.user_id == ctx.user.user_id,
                    CalendarOperation.session_key == ctx.session_state.get("calendar_session_key", ""),
                    CalendarOperation.status == "pending",
                    CalendarOperation.expires_at > datetime.now(UTC),
                    no_other if require_unique else true(),
                )
                .values(status="running")
            )
            return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    async def finish(self, ctx: ToolContext, operation_id: str, status: str, result: dict[str, Any]) -> None:
        async with self.db.session() as session:
            operation = await session.get(CalendarOperation, operation_id)
            if operation is None or operation.user_id != ctx.user.user_id:
                return
            operation.status = status
            operation.result = result
            await AuditRepository(session).record(
                user_id=ctx.user.user_id,
                action=f"calendar:{operation.payload['action']}",
                resource="correo:calendario",
                outcome=status,
                request_id=ctx.request_id,
                detail={
                    "operation_id": operation_id,
                    "provider": operation.provider,
                    "event_id": result.get("event_id") or operation.payload.get("event_id"),
                    "error_type": result.get("error_type"),
                },
            )
