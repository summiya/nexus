"""Add tenant-safe, versioned V1 chunk embeddings without activating retrieval.

Revision ID: 20261103_0020
Revises: 20261007_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "20261103_0020"
down_revision: str | None = "20261007_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The deployment role must have extension privileges. An unavailable or
    # disallowed extension must fail the migration, never silently skip vectors.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_unique_constraint(
        "uq_document_chunks_id_organization_id",
        "document_chunks",
        ["id", "organization_id"],
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_id", sa.BigInteger(), nullable=False),
        sa.Column("configured_model_id", sa.BigInteger(), nullable=False),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("provider_model_name", sa.String(256), nullable=False),
        sa.Column("embedding_dimension", sa.BigInteger(), nullable=False),
        sa.Column("embedding_generation", sa.BigInteger(), nullable=False),
        sa.Column("embedding_version", sa.String(128), nullable=False),
        sa.Column("embedding", VECTOR(1536), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunk_embeddings"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_chunk_embeddings_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id", "organization_id"],
            ["document_chunks.id", "document_chunks.organization_id"],
            name="fk_chunk_embeddings_chunk_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "model_type", "configured_model_id"],
            [
                "configured_models.organization_id",
                "configured_models.model_type",
                "configured_models.id",
            ],
            name="fk_chunk_embeddings_tenant_embedding_model",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "model_type = 'embedding'", name="ck_chunk_embeddings_model_type"
        ),
        # These checks constrain the declared historical invocation profile;
        # they do not verify it against mutable configured-model/provider rows.
        sa.CheckConstraint(
            "provider_type = 'openai' AND "
            "provider_model_name = 'text-embedding-3-small'",
            name="ck_chunk_embeddings_v1_model_snapshot",
        ),
        sa.CheckConstraint(
            "embedding_dimension = 1536", name="ck_chunk_embeddings_dimension"
        ),
        sa.CheckConstraint(
            "embedding_generation > 0", name="ck_chunk_embeddings_generation"
        ),
        sa.CheckConstraint(
            "embedding_version ~ '\\S' "
            "AND embedding_version !~ '^[[:space:]]' "
            "AND embedding_version !~ '[[:space:]]$'",
            name="ck_chunk_embeddings_version",
        ),
        sa.CheckConstraint(
            "vector_norm(embedding) > 0", name="ck_chunk_embeddings_nonzero_vector"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "chunk_id",
            "configured_model_id",
            "embedding_generation",
            name="uq_chunk_embeddings_generation",
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_organization_model_generation",
        "chunk_embeddings",
        ["organization_id", "configured_model_id", "embedding_generation"],
    )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.drop_constraint(
        "uq_document_chunks_id_organization_id", "document_chunks", type_="unique"
    )
    # vector may predate RF-04 or have other consumers. Never DROP EXTENSION,
    # especially with CASCADE; only RF-04's table and parent key are owned here.
