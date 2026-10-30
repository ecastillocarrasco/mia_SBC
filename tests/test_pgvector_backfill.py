"""PostgreSQL binding and float32 preservation in both directions of migration 0011."""

from importlib import import_module

import numpy as np
import pytest
import sqlalchemy as sa

from mia.data import Database
from tests.dbutil import POSTGRES_URL


@pytest.mark.skipif(not POSTGRES_URL, reason="Requires the dedicated PostgreSQL test database")
async def test_embedding_backfill_preserves_values_and_nulls(monkeypatch):
    migration = import_module("migrations.versions.0011_migracion_a_pgvector")
    values = np.linspace(-1.0, 1.0, migration.DIM, dtype=np.float32)
    raw = values.tobytes()
    db = Database(POSTGRES_URL)

    def roundtrip(conn):
        # Temporary table is private to this transaction and never touches application rows.
        conn.execute(
            sa.text(
                "CREATE TEMP TABLE ci_embedding_roundtrip "
                "(id integer PRIMARY KEY, embedding bytea, embedding_vec vector(1536)) ON COMMIT DROP"
            )
        )
        table = migration._embedding_table("ci_embedding_roundtrip")
        conn.execute(table.insert(), [{"id": 1, "embedding": raw}, {"id": 2, "embedding": None}])
        monkeypatch.setattr(migration.op, "get_bind", lambda: conn)
        migration._backfill_up("ci_embedding_roundtrip")
        converted = conn.execute(sa.select(table.c.embedding_vec).where(table.c.id == 1)).scalar_one()
        np.testing.assert_array_equal(np.asarray(converted, dtype=np.float32), values)
        conn.execute(table.update().values(embedding=None))
        migration._backfill_down("ci_embedding_roundtrip")
        restored = conn.execute(sa.select(table.c.id, table.c.embedding).order_by(table.c.id)).all()
        assert restored == [(1, raw), (2, None)]

    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(roundtrip)
    finally:
        await db.dispose()
