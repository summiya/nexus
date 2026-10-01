"""Document persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class Document(Base):
    """Persisted Document identity and processing lifecycle."""

    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_file_id", "organization_id"],
            ["files.id", "files.organization_id"],
            name="fk_documents_source_file_organization_files",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "public_id <> '00000000-0000-0000-0000-000000000000'::uuid",
            name="ck_documents_public_id_nonzero",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "processing_version IS NULL OR ("
            "processing_version ~ '\\S' "
            "AND processing_version !~ '^[[:space:]]' "
            "AND processing_version !~ '[[:space:]]$')",
            name="ck_documents_processing_version",
        ),
        CheckConstraint(
            "extractor_version IS NULL OR ("
            "extractor_version ~ '\\S' "
            "AND extractor_version !~ '^[[:space:]]' "
            "AND extractor_version !~ '[[:space:]]$')",
            name="ck_documents_extractor_version",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]*$'",
            name="ck_documents_failure_code_format",
        ),
        CheckConstraint(
            "failure_safe_message IS NULL OR failure_safe_message ~ '\\S'",
            name="ck_documents_failure_message_nonblank",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "(processing_started_at IS NULL OR processing_started_at >= created_at) "
            "AND (processing_completed_at IS NULL "
            "OR processing_completed_at >= processing_started_at) "
            "AND (failed_at IS NULL OR failed_at >= processing_started_at)",
            name="ck_documents_timestamp_order",
        ),
        UniqueConstraint("public_id", name="uq_documents_public_id"),
        Index(
            "ix_documents_source_file_id_organization_id",
            "source_file_id",
            "organization_id",
        ),
        Index(
            "uq_documents_active_source_file_id",
            "source_file_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'processing')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "organizations.id",
            name="fk_documents_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_safe_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
