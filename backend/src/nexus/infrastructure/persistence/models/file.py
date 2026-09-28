"""File persistence model."""

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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class File(Base):
    """Persisted File ownership and provider-neutral storage metadata."""

    __tablename__ = "files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_files_creator_organization_users",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "original_name ~ '\\S'",
            name="ck_files_original_name_nonblank",
        ),
        CheckConstraint(
            "mime_type ~ '\\S'",
            name="ck_files_mime_type_nonblank",
        ),
        CheckConstraint(
            "storage_key ~ '\\S'",
            name="ck_files_storage_key_nonblank",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_files_size_bytes_nonnegative",
        ),
        CheckConstraint(
            "storage_status IN ('pending', 'available', 'failed', 'deleting')",
            name="ck_files_storage_status",
        ),
        CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_files_checksum_sha256_format",
        ),
        CheckConstraint(
            "storage_status <> 'available' OR size_bytes IS NOT NULL",
            name="ck_files_available_size",
        ),
        UniqueConstraint("public_id", name="uq_files_public_id"),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_files_id_organization_id",
        ),
        UniqueConstraint("storage_key", name="uq_files_storage_key"),
        Index(
            "ix_files_organization_created_at_public_id",
            "organization_id",
            "created_at",
            "public_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, default=uuid.uuid4
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "organizations.id",
            name="fk_files_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
