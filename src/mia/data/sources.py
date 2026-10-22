"""Réplica de las fuentes y estado de sincronización."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from mia.data.models import Base, _now


class SourceItem(Base):
    """Copia del elemento tal como llega de la fuente (con los identificadores seudonimizados)."""

    __tablename__ = "source_items"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SourceSyncState(Base):
    __tablename__ = "source_sync_state"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="never")
    """never · ok · error"""
    change_token: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    last_full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_incremental_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_changes: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


STALE_AFTER = timedelta(minutes=30)


async def freshness(db: AsyncSession, *sources: str, stale_after: timedelta = STALE_AFTER) -> dict[str, Any]:
    """Antigüedad de las fuentes consultadas. ``al_dia`` False solo si superan el umbral.

    Genérico sobre ``SourceSyncState``: lo usa cualquier dominio sincronizado desde SharePoint
    (RRHH, Community…), nunca solo uno — por eso vive aquí y no en el ``common.py`` de un dominio
    concreto."""
    states = {
        s.source: s
        for s in (await db.scalars(select(SourceSyncState).where(SourceSyncState.source.in_(sources)))).all()
    }
    now = datetime.now(UTC)
    oldest: int | None = 0
    never: list[str] = []
    for source in sources:
        state = states.get(source)
        last = state.last_success_at if state else None
        if last is None:
            never.append(source)
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        minutes = int((now - last).total_seconds() // 60)
        oldest = max(oldest or 0, minutes)
    if never:
        return {"al_dia": False, "aviso": "Estas fuentes no se han sincronizado nunca: " + ", ".join(never)}
    if oldest is not None and oldest > stale_after.total_seconds() // 60:
        return {
            "al_dia": False,
            "aviso": f"Última sincronización hace {oldest} minutos: pueden faltar cambios recientes.",
        }
    return {"al_dia": True}
