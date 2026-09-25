"""Trusted File upload-attempt persistence model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class FileUploadAttempt(Base):
    """Trusted declaration and grant lifetime for one File upload attempt."""

    __tablename__ = "file_upload_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["file_id", "organization_id"],
            ["files.id", "files.organization_id"],
            name="fk_file_upload_attempts_file_organization_files",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "declared_size_bytes >= 0",
            name="ck_file_upload_attempts_declared_size_bytes_nonnegative",
        ),
        CheckConstraint(
            "grant_expires_at > created_at",
            name="ck_file_upload_attempts_grant_expires_after_created_at",
        ),
        Index(
            "ix_file_upload_attempts_organization_file_created_at",
            "organization_id",
            "file_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grant_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
