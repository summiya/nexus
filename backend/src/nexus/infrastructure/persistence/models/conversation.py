"""Conversation persistence model."""

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
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class Conversation(Base):
    """Persisted Conversation container and scope metadata."""

    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_conversations_creator_organization_users",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "project_public_id IS NULL OR workspace_public_id IS NOT NULL",
            name="ck_conversations_project_requires_workspace",
        ),
        UniqueConstraint("public_id", name="uq_conversations_public_id"),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_conversations_id_organization_id",
        ),
        Index(
            "ix_conversations_creator_created_at",
            "organization_id",
            "created_by_user_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_conversations_workspace_created_at",
            "organization_id",
            "workspace_public_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_conversations_project_created_at",
            "organization_id",
            "project_public_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, default=uuid.uuid4
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_public_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    project_public_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
