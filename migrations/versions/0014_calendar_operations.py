"""Propuestas de agenda y protección de operaciones frente a duplicados.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_operations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("session_key", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("result", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
    )
    op.create_index("ix_calendar_operations_user_id", "calendar_operations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_operations_user_id", table_name="calendar_operations")
    op.drop_table("calendar_operations")
