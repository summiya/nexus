"""Create Document persistence table.

Revision ID: 20261001_0015
Revises: 20260929_0014
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0015"
down_revision: str | None = "20260929_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("processing_version", sa.String(length=128), nullable=True),
        sa.Column("extractor_version", sa.String(length=128), nullable=True),
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "processing_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_safe_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_documents_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id", "organization_id"],
            ["files.id", "files.organization_id"],
            name="fk_documents_source_file_organization_files",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "public_id <> '00000000-0000-0000-0000-000000000000'::uuid",
            name="ck_documents_public_id_nonzero",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_documents_status",
        ),
        sa.CheckConstraint(
            "processing_version IS NULL OR ("
            "processing_version ~ '\\S' "
            "AND processing_version !~ '^[[:space:]]' "
            "AND processing_version !~ '[[:space:]]$')",
            name="ck_documents_processing_version",
        ),
        sa.CheckConstraint(
            "extractor_version IS NULL OR ("
            "extractor_version ~ '\\S' "
            "AND extractor_version !~ '^[[:space:]]' "
            "AND extractor_version !~ '[[:space:]]$')",
            name="ck_documents_extractor_version",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]*$'",
            name="ck_documents_failure_code_format",
        ),
        sa.CheckConstraint(
            "failure_safe_message IS NULL OR failure_safe_message ~ '\\S'",
            name="ck_documents_failure_message_nonblank",
        ),
        sa.CheckConstraint(
            "(status = 'queued' "
            "AND processing_version IS NULL "
            "AND extractor_version IS NULL "
            "AND processing_started_at IS NULL "
            "AND processing_completed_at IS NULL "
            "AND failed_at IS NULL "
            "AND failure_code IS NULL "
            "AND failure_safe_message IS NULL) OR "
            "(status = 'processing' "
            "AND processing_version IS NOT NULL "
            "AND processing_started_at IS NOT NULL "
            "AND processing_completed_at IS NULL "
            "AND failed_at IS NULL "
            "AND failure_code IS NULL "
            "AND failure_safe_message IS NULL) OR "
            "(status = 'completed' "
            "AND processing_version IS NOT NULL "
            "AND processing_started_at IS NOT NULL "
            "AND processing_completed_at IS NOT NULL "
            "AND failed_at IS NULL "
            "AND failure_code IS NULL "
            "AND failure_safe_message IS NULL) OR "
            "(status = 'failed' "
            "AND processing_version IS NOT NULL "
            "AND processing_started_at IS NOT NULL "
            "AND processing_completed_at IS NULL "
            "AND failed_at IS NOT NULL "
            "AND failure_code IS NOT NULL "
            "AND failure_safe_message IS NOT NULL)",
            name="ck_documents_lifecycle_metadata",
        ),
        sa.CheckConstraint(
            "(processing_started_at IS NULL OR processing_started_at >= created_at) "
            "AND (processing_completed_at IS NULL "
            "OR processing_completed_at >= processing_started_at) "
            "AND (failed_at IS NULL OR failed_at >= processing_started_at)",
            name="ck_documents_timestamp_order",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_documents_id_organization_id",
        ),
        sa.UniqueConstraint("public_id", name="uq_documents_public_id"),
    )
    op.create_index(
        "ix_documents_source_file_id_organization_id",
        "documents",
        ["source_file_id", "organization_id"],
    )
    op.create_index(
        "uq_documents_active_source_file_id",
        "documents",
        ["source_file_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_documents_active_source_file_id",
        table_name="documents",
    )
    op.drop_index(
        "ix_documents_source_file_id_organization_id",
        table_name="documents",
    )
    op.drop_table("documents")
