"""Base de datos para los tests: SQLite por defecto; PostgreSQL si MIA_TEST_DATABASE_URL está definido.

La integración continua ejecuta la batería completa también contra PostgreSQL,
que aplica restricciones (longitudes, tipos) que SQLite ignora.
"""

from __future__ import annotations

import os
from pathlib import Path

from mia.data import Base, Database

POSTGRES_URL = os.environ.get("MIA_TEST_DATABASE_URL")


def test_database_url(tmp_path: Path, name: str = "test.db") -> str:
    return POSTGRES_URL or f"sqlite+aiosqlite:///{tmp_path / name}"


async def fresh_database(tmp_path: Path, name: str = "test.db") -> Database:
    db = Database(test_database_url(tmp_path, name))
    async with db.engine.begin() as conn:
        if POSTGRES_URL:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return db
