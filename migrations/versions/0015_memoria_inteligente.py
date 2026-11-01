"""Memoria Inteligente V1: recuerdos manuales por usuario y su interruptor.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_memories_user_created", "user_memories", ["user_id", "created_at"])
    op.create_table(
        "memory_preferences",
        sa.Column("user_id", sa.String(128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("memory_preferences")
    op.drop_index("ix_user_memories_user_created", table_name="user_memories")
    op.drop_table("user_memories")
