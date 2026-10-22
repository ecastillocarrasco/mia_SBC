"""Piezas compartidas por los dominios de Community."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import Database
from mia.data.sources import STALE_AFTER
from mia.data.sources import freshness as _freshness


@dataclass(frozen=True, slots=True)
class Deps:
    db: Database
    stale_after: timedelta = STALE_AFTER

    async def freshness(self, db: AsyncSession, *sources: str) -> dict[str, Any]:
        return await _freshness(db, *sources, stale_after=self.stale_after)
