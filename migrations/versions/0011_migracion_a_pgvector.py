"""migracion a pgvector: columnas vector(1536) + indice hnsw, backfill de embeddings existentes

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import numpy as np
import sqlalchemy as sa
from alembic import context, op
from pgvector.sqlalchemy import Vector

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = 1536
BATCH = 500


def _vec_literal(blob: bytes) -> str:
    """bytes (float32 empaquetado por ``pack()``) -> literal de texto que ``::vector`` acepta."""
    floats = np.frombuffer(blob, dtype=np.float32)
    return "[" + ",".join(repr(float(x)) for x in floats) + "]"


def _embedding_table(name: str) -> sa.TableClause:
    return sa.table(
        name,
        sa.column("id", sa.Integer()),
        sa.column("embedding", sa.LargeBinary()),
        sa.column("embedding_vec", Vector(DIM)),
    )


def _backfill_up(table: str) -> None:
    bind = op.get_bind()
    source = _embedding_table(table)
    rows = bind.execute(sa.select(source.c.id, source.c.embedding).where(source.c.embedding.is_not(None))).fetchall()
    statement = (
        source.update()
        .where(source.c.id == sa.bindparam("row_id"))
        .values(embedding_vec=sa.cast(sa.bindparam("vec", type_=sa.Text()), Vector(DIM)))
    )
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        bind.execute(statement, [{"row_id": row.id, "vec": _vec_literal(row.embedding)} for row in batch])


def _backfill_down(table: str) -> None:
    bind = op.get_bind()
    source = _embedding_table(table)
    rows = bind.execute(
        sa.select(source.c.id, source.c.embedding_vec).where(source.c.embedding_vec.is_not(None))
    ).fetchall()
    statement = source.update().where(source.c.id == sa.bindparam("row_id")).values(embedding=sa.bindparam("raw"))
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        params = [{"row_id": row.id, "raw": np.asarray(row.embedding_vec, dtype=np.float32).tobytes()} for row in batch]
        bind.execute(statement, params)


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    # SQLite no tiene la extensión, el operador <=> ni índices HNSW — pero sí sabe crear la columna
    # (pgvector.sqlalchemy.Vector cae a NUMERIC ahí), así que test_upgrade_matches_models (que corre
    # esta migración contra SQLite para comparar el esquema con los modelos) sigue funcionando. El
    # backfill de datos reales (bytes -> vector) solo tiene sentido, y solo se ejecuta, en Postgres.
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    for table in ("hr_cv_chunks", "hr_document_chunks"):
        op.add_column(table, sa.Column("embedding_vec", Vector(DIM), nullable=True))

    if is_postgres and not context.is_offline_mode():
        _backfill_up("hr_cv_chunks")
        _backfill_up("hr_document_chunks")

    for table in ("hr_cv_chunks", "hr_document_chunks"):
        op.drop_column(table, "embedding")
        op.alter_column(table, "embedding_vec", new_column_name="embedding")
        if is_postgres:
            op.execute(f"CREATE INDEX ix_{table}_embedding_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    for table in ("hr_cv_chunks", "hr_document_chunks"):
        if is_postgres:
            op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_hnsw")
        op.alter_column(table, "embedding", new_column_name="embedding_vec")
        op.add_column(table, sa.Column("embedding", sa.LargeBinary(), nullable=True))

    if is_postgres and not context.is_offline_mode():
        _backfill_down("hr_cv_chunks")
        _backfill_down("hr_document_chunks")

    for table in ("hr_cv_chunks", "hr_document_chunks"):
        op.drop_column(table, "embedding_vec")
