"""Durable indexing headers, independent of Document processing state."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class IndexingGeneration(Base):
    __tablename__ = "indexing_generations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["document_chunk_sets.document_id", "document_chunk_sets.organization_id"],
            name="fk_indexing_generations_chunk_set",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "model_type", "configured_model_id"],
            [
                "configured_models.organization_id",
                "configured_models.model_type",
                "configured_models.id",
            ],
            name="fk_indexing_generations_tenant_embedding_model",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "model_type = 'embedding'", name="ck_indexing_generations_model_type"
        ),
        CheckConstraint(
            "embedding_generation > 0 AND embedding_dimension > 0",
            name="ck_indexing_generations_positive_values",
        ),
        CheckConstraint(
            "provider_type ~ '\\S' AND provider_type !~ '^[[:space:]]|[[:space:]]$' "
            "AND provider_model_name ~ '\\S' AND provider_model_name !~ '^[[:space:]]|[[:space:]]$' "
            "AND embedding_version ~ '\\S' AND embedding_version !~ '^[[:space:]]|[[:space:]]$'",
            name="ck_indexing_generations_snapshot",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_indexing_generations_status",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]*$'",
            name="ck_indexing_generations_failure_code",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'processing' AND started_at IS NOT NULL AND finished_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_indexing_generations_lifecycle",
        ),
        CheckConstraint(
            "(started_at IS NULL OR started_at >= created_at) AND "
            "(finished_at IS NULL OR finished_at >= coalesce(started_at, created_at))",
            name="ck_indexing_generations_timestamp_order",
        ),
        Index(
            "uq_indexing_generations_active",
            "organization_id",
            "document_id",
            "configured_model_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
    )

    organization_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    configured_model_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    embedding_generation: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
