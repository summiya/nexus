"""Conversation message domain contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ConversationMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class Message:
    """Durable conversational content."""

    public_id: UUID
    conversation_public_id: UUID
    role: ConversationMessageRole
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("message content must not be empty")
        _require_timezone_aware(self.created_at, "created_at")
