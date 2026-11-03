"""Versioned vectors; snapshot authenticity belongs to the trusted future writer.

Foreign keys enforce tenant and model-type relationships, not correspondence
between historical invocation snapshots and mutable provider configuration.
"""

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "organization_id"],
            ["document_chunks.id", "document_chunks.organization_id"],
            name="fk_chunk_embeddings_chunk_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "model_type", "configured_model_id"],
            [
                "configured_models.organization_id",
                "configured_models.model_type",
                "configured_models.id",
            ],
            name="fk_chunk_embeddings_tenant_embedding_model",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "model_type = 'embedding'", name="ck_chunk_embeddings_model_type"
        ),
        CheckConstraint(
            "provider_type = 'openai' AND "
            "provider_model_name = 'text-embedding-3-small'",
            name="ck_chunk_embeddings_v1_model_snapshot",
        ),
        CheckConstraint(
            "embedding_dimension = 1536", name="ck_chunk_embeddings_dimension"
        ),
        CheckConstraint(
            "embedding_generation > 0", name="ck_chunk_embeddings_generation"
        ),
        CheckConstraint(
            "embedding_version ~ '\\S' "
            "AND embedding_version !~ '^[[:space:]]' "
            "AND embedding_version !~ '[[:space:]]$'",
            name="ck_chunk_embeddings_version",
        ),
        CheckConstraint(
            "vector_norm(embedding) > 0", name="ck_chunk_embeddings_nonzero_vector"
        ),
        UniqueConstraint(
            "organization_id",
            "chunk_id",
            "configured_model_id",
            "embedding_generation",
            name="uq_chunk_embeddings_generation",
        ),
        Index(
            "ix_chunk_embeddings_organization_model_generation",
            "organization_id",
            "configured_model_id",
            "embedding_generation",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "organizations.id",
            name="fk_chunk_embeddings_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    chunk_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    configured_model_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
