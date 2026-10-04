"""Operación: estado de las fuentes sincronizadas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from mia.api.deps import ServicesDep, require
from mia.auth import Permission, UserContext
from mia.data import SourceSyncState
from mia.sources import all_sources

router = APIRouter(prefix="/api/admin", tags=["operación"])

STALE_AFTER_MINUTES = 30

AdminDep = Annotated[UserContext, Depends(require(Permission.ADMINISTRAR))]


@router.get("/sources")
async def sources(services: ServicesDep, _: AdminDep) -> list[dict[str, Any]]:
    async with services.db.session() as db:
        states = {s.source: s for s in (await db.scalars(select(SourceSyncState))).all()}
    now = datetime.now(UTC)
    result = []
    for source in all_sources():
        state = states.get(source.key)
        age = None
        if state and state.last_success_at:
            last = (
                state.last_success_at
                if state.last_success_at.tzinfo
                else state.last_success_at.replace(tzinfo=UTC)
            )
            age = int((now - last).total_seconds() // 60)
        result.append(
            {
                "source": source.key,
                "list": source.list_title,
                "status": state.status if state else "never",
                "items": state.item_count if state else 0,
                "last_success_at": state.last_success_at if state else None,
                "minutes_since_success": age,
                "stale": age is None or age > STALE_AFTER_MINUTES,
                "last_error": state.last_error if state else None,
            }
        )
    return result
