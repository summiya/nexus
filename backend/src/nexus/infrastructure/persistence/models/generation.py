"""Generation persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class Generation(Base):
    """Persisted LLM generation attempt."""

    __tablename__ = "generations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["conversations.id", "conversations.organization_id"],
            name="fk_generations_conversation_organization_conversations",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "organization_id"],
            ["messages.id", "messages.conversation_id", "messages.organization_id"],
            name="fk_generations_user_message_scope_messages",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["assistant_message_id", "conversation_id", "organization_id"],
            ["messages.id", "messages.conversation_id", "messages.organization_id"],
            name="fk_generations_assistant_message_scope_messages",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_generations_status",
        ),
        CheckConstraint(
            "finish_reason IS NULL OR finish_reason IN "
            "('stop', 'length', 'tool_calls', 'content_filter', 'unknown')",
            name="ck_generations_finish_reason",
        ),
        CheckConstraint(
            "btrim(model) <> ''",
            name="ck_generations_model_nonblank",
        ),
        CheckConstraint(
            "input_tokens >= 0",
            name="ck_generations_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens >= 0",
            name="ck_generations_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens >= 0",
            name="ck_generations_total_tokens_nonnegative",
        ),
        CheckConstraint(
            "error_kind IS NULL OR btrim(error_kind) <> ''",
            name="ck_generations_error_kind_nonblank",
        ),
        UniqueConstraint("public_id", name="uq_generations_public_id"),
        Index(
            "ix_generations_conversation_created_at",
            "organization_id",
            "conversation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, default=uuid.uuid4
    )
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    assistant_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
