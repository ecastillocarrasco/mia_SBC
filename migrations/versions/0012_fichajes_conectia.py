"""fichajes (control de presencia) — importación Excel de Conectia

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_clock_marks",
        sa.Column("person_key", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(length=64), nullable=True),
        sa.Column("device_type", sa.String(length=32), nullable=True),
        sa.Column("terminal_name", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("person_key", "at"),
    )
    with op.batch_alter_table("hr_clock_marks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_hr_clock_marks_person_at"), ["person_key", "at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("hr_clock_marks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_hr_clock_marks_person_at"))
    op.drop_table("hr_clock_marks")
