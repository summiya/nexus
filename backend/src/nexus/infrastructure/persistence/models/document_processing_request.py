"""Durable initial-ingestion marker and pending processing outbox record."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class DocumentProcessingRequest(Base):
    """Small source-verification record, retained after eventual dispatch."""

    __tablename__ = "document_processing_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id", "source_file_id"],
            ["documents.id", "documents.organization_id", "documents.source_file_id"],
            name="fk_document_requests_document_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("public_id", name="uq_document_requests_public_id"),
        Index("ix_document_requests_source_file_id", "source_file_id", "id"),
        UniqueConstraint("document_id", name="uq_document_requests_document"),
        CheckConstraint(
            "public_id <> '00000000-0000-0000-0000-000000000000'::uuid",
            name="ck_document_requests_public_id_nonzero",
        ),
        CheckConstraint(
            "source_entity_tag ~ '\\S'", name="ck_document_requests_entity_tag"
        ),
        CheckConstraint("expected_size_bytes >= 0", name="ck_document_requests_size"),
        CheckConstraint(
            "dispatched_at IS NULL OR dispatched_at >= created_at",
            name="ck_document_requests_timestamp_order",
        ),
        CheckConstraint("dispatch_attempts >= 0", name="ck_document_requests_attempts"),
        CheckConstraint(
            "(dispatch_lease_token IS NULL) = (dispatch_lease_until IS NULL)",
            name="ck_document_requests_lease_pair",
        ),
        Index(
            "ix_document_requests_pending",
            "dispatch_next_attempt_at",
            "id",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_entity_tag: Mapped[str] = mapped_column(String(1024), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    dispatch_lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    dispatch_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatch_next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    dispatch_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
