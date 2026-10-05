"""Add durable initial Document processing requests.

Revision ID: 20261005_0016
Revises: 20261001_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_0016"
down_revision: str | None = "20261001_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_documents_id_organization_source",
        "documents",
        ["id", "organization_id", "source_file_id"],
    )
    op.create_table(
        "document_processing_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("source_entity_tag", sa.String(1024), nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document_processing_requests"),
        sa.ForeignKeyConstraint(
            ["document_id", "organization_id", "source_file_id"],
            ["documents.id", "documents.organization_id", "documents.source_file_id"],
            name="fk_document_requests_document_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("public_id", name="uq_document_requests_public_id"),
        sa.UniqueConstraint("source_file_id", name="uq_document_requests_initial_file"),
        sa.UniqueConstraint("document_id", name="uq_document_requests_document"),
        sa.CheckConstraint(
            "public_id <> '00000000-0000-0000-0000-000000000000'::uuid",
            name="ck_document_requests_public_id_nonzero",
        ),
        sa.CheckConstraint(
            "source_entity_tag ~ '\\S'", name="ck_document_requests_entity_tag"
        ),
        sa.CheckConstraint(
            "expected_size_bytes >= 0", name="ck_document_requests_size"
        ),
        sa.CheckConstraint(
            "dispatched_at IS NULL OR dispatched_at >= created_at",
            name="ck_document_requests_timestamp_order",
        ),
    )
    op.create_index(
        "ix_document_requests_pending",
        "document_processing_requests",
        ["created_at", "id"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("document_processing_requests")
    op.drop_constraint(
        "uq_documents_id_organization_source", "documents", type_="unique"
    )
