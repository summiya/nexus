"""Typed records returned by persisted Conversation history reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.conversations.domain.generation import (
    GenerationFinishReason,
    GenerationStatus,
)
from nexus.conversations.domain.message import Message


@dataclass(frozen=True)
class ConversationGenerationMetadata:
    """Generation fields relevant to a persisted assistant Message."""

    public_id: UUID
    model: str
    status: GenerationStatus
    finish_reason: GenerationFinishReason | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    started_at: datetime | None
    completed_at: datetime | None
    error_kind: str | None


@dataclass(frozen=True)
class ConversationMessageHistoryItem:
    """One persisted Message and its optional producing Generation."""

    message: Message
    generation: ConversationGenerationMetadata | None
