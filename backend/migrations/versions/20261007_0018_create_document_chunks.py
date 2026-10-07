"""Persist one complete chunk set per Document lifecycle.

Revision ID: 20261007_0018
Revises: 20261005_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261007_0018"
down_revision: str | None = "20261005_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunk_sets",
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("source_entity_tag", sa.String(1024), nullable=False),
        sa.Column("extractor_id", sa.String(1024), nullable=False),
        sa.Column("extractor_version", sa.String(1024), nullable=False),
        sa.Column("normalizer_id", sa.String(1024), nullable=False),
        sa.Column("normalizer_version", sa.String(1024), nullable=False),
        sa.Column("segmenter_id", sa.String(1024), nullable=False),
        sa.Column("segmenter_version", sa.String(1024), nullable=False),
        sa.Column("preferred_chunk_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_chunk_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_source_contributions", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.BigInteger(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("document_id", name="pk_document_chunk_sets"),
        sa.UniqueConstraint(
            "document_id",
            "organization_id",
            name="uq_document_chunk_sets_document_organization",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.id", "documents.organization_id"],
            name="fk_document_chunk_sets_document_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("chunk_count > 0", name="ck_document_chunk_sets_count"),
        sa.CheckConstraint(
            "preferred_chunk_bytes > 0 AND max_chunk_bytes >= preferred_chunk_bytes AND max_source_contributions > 0",
            name="ck_document_chunk_sets_settings",
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0", name="ck_document_chunk_sets_pages"
        ),
        sa.CheckConstraint(
            "source_entity_tag ~ '\\S' AND extractor_id ~ '\\S' AND extractor_version ~ '\\S' AND normalizer_id ~ '\\S' AND normalizer_version ~ '\\S' AND segmenter_id ~ '\\S' AND segmenter_version ~ '\\S'",
            name="ck_document_chunk_sets_metadata",
        ),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("section_path", sa.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("contributions", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_index"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["document_chunk_sets.document_id", "document_chunk_sets.organization_id"],
            name="fk_document_chunks_set_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index"),
        sa.CheckConstraint("text ~ '\\S'", name="ck_document_chunks_text"),
        sa.CheckConstraint(
            "kind IN ('text', 'paragraph', 'list', 'code', 'raw', 'heading')",
            name="ck_document_chunks_kind",
        ),
        sa.CheckConstraint(
            "cardinality(section_path) <= 6", name="ck_document_chunks_section_path"
        ),
        sa.CheckConstraint(
            "CASE WHEN jsonb_typeof(contributions) = 'array' THEN jsonb_array_length(contributions) > 0 ELSE false END",
            name="ck_document_chunks_contributions",
        ),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("document_chunk_sets")
