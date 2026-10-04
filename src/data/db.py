"""Conexión a base de datos (PostgreSQL en Azure; SQLite solo en tests)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        options: dict[str, object] = {"echo": echo}
        if url.startswith("postgresql"):
            options |= {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True, "pool_recycle": 1800}
        self.engine: AsyncEngine = create_async_engine(url, **options)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
