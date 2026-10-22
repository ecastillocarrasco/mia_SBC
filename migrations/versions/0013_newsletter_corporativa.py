"""community: newsletter corporativa (SharePoint NewsletterCorporativa)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_newsletter_items",
        sa.Column("sp_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("image_url", sa.String(length=1024), nullable=True),
        sa.Column("link_url", sa.String(length=1024), nullable=True),
        sa.Column("button_text", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("sp_id"),
    )


def downgrade() -> None:
    op.drop_table("community_newsletter_items")
