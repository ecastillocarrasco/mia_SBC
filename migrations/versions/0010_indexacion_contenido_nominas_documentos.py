"""indexacion de contenido de nominas y documentos firmados (texto/fragmentos/embeddings)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hr_payslips", schema=None) as batch_op:
        batch_op.add_column(sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("hr_signed_documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "hr_document_texts",
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("person_key", sa.String(length=64), nullable=True),
        sa.Column("source_modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("domain", "document_id"),
    )
    with op.batch_alter_table("hr_document_texts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_hr_document_texts_person_key"), ["person_key"], unique=False)

    op.create_table(
        "hr_document_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("person_key", sa.String(length=64), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("hr_document_chunks", schema=None) as batch_op:
        batch_op.create_index("ix_hr_document_chunks_domain_document", ["domain", "document_id"], unique=False)
        batch_op.create_index("ix_hr_document_chunks_domain_person", ["domain", "person_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("hr_document_chunks", schema=None) as batch_op:
        batch_op.drop_index("ix_hr_document_chunks_domain_person")
        batch_op.drop_index("ix_hr_document_chunks_domain_document")
    op.drop_table("hr_document_chunks")

    with op.batch_alter_table("hr_document_texts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_hr_document_texts_person_key"))
    op.drop_table("hr_document_texts")

    with op.batch_alter_table("hr_signed_documents", schema=None) as batch_op:
        batch_op.drop_column("modified_at")
    with op.batch_alter_table("hr_payslips", schema=None) as batch_op:
        batch_op.drop_column("modified_at")
