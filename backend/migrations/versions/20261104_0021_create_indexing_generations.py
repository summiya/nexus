"""Add independent durable indexing state without adopting legacy vectors.

Revision ID: 20261104_0021
Revises: 20261103_0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0021"
down_revision: str | None = "20261103_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indexing_generations",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("configured_model_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "embedding_generation", sa.BigInteger(), autoincrement=False, nullable=False
        ),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("provider_model_name", sa.String(256), nullable=False),
        sa.Column("embedding_dimension", sa.BigInteger(), nullable=False),
        sa.Column("embedding_version", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "document_id",
            "configured_model_id",
            "embedding_generation",
            name="pk_indexing_generations",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["document_chunk_sets.document_id", "document_chunk_sets.organization_id"],
            name="fk_indexing_generations_chunk_set",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "model_type", "configured_model_id"],
            [
                "configured_models.organization_id",
                "configured_models.model_type",
                "configured_models.id",
            ],
            name="fk_indexing_generations_tenant_embedding_model",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "model_type = 'embedding'", name="ck_indexing_generations_model_type"
        ),
        sa.CheckConstraint(
            "embedding_generation > 0 AND embedding_dimension > 0",
            name="ck_indexing_generations_positive_values",
        ),
        sa.CheckConstraint(
            "provider_type ~ '\\S' AND provider_type !~ '^[[:space:]]|[[:space:]]$' "
            "AND provider_model_name ~ '\\S' AND provider_model_name !~ '^[[:space:]]|[[:space:]]$' "
            "AND embedding_version ~ '\\S' AND embedding_version !~ '^[[:space:]]|[[:space:]]$'",
            name="ck_indexing_generations_snapshot",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_indexing_generations_status",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]*$'",
            name="ck_indexing_generations_failure_code",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'processing' AND started_at IS NOT NULL AND finished_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_indexing_generations_lifecycle",
        ),
        sa.CheckConstraint(
            "(started_at IS NULL OR started_at >= created_at) AND "
            "(finished_at IS NULL OR finished_at >= coalesce(started_at, created_at))",
            name="ck_indexing_generations_timestamp_order",
        ),
    )
    op.create_index(
        "uq_indexing_generations_active",
        "indexing_generations",
        ["organization_id", "document_id", "configured_model_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    # Only lifecycle history is discarded. Vectors, sources and vector extension remain.
    op.drop_table("indexing_generations")
