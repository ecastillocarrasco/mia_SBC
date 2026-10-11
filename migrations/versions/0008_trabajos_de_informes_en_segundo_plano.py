"""trabajos de informes en segundo plano (Job Manager)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("progress_message", sa.String(length=256), nullable=True),
        sa.Column("report_id", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("report_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_report_jobs_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_report_jobs_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_report_jobs_idempotency_key"), ["idempotency_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("report_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_report_jobs_idempotency_key"))
        batch_op.drop_index(batch_op.f("ix_report_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_report_jobs_user_id"))
    op.drop_table("report_jobs")
