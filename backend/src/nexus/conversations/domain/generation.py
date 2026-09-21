"""Conversation generation domain contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class GenerationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationFinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_optional_timezone_aware(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None:
        _require_timezone_aware(value, field_name)


@dataclass(frozen=True)
class Generation:
    """One attempt to produce an assistant response."""

    public_id: UUID
    conversation_public_id: UUID
    user_message_public_id: UUID
    model: str
    status: GenerationStatus
    idempotency_key: UUID | None = None
    assistant_message_public_id: UUID | None = None
    finish_reason: GenerationFinishReason | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("generation model must not be empty")
        if self.input_tokens < 0:
            raise ValueError("input_tokens must not be negative")
        if self.output_tokens < 0:
            raise ValueError("output_tokens must not be negative")
        if self.total_tokens < 0:
            raise ValueError("total_tokens must not be negative")
        if self.error_kind is not None and not self.error_kind.strip():
            raise ValueError("error_kind must not be empty")
        _require_optional_timezone_aware(self.started_at, "started_at")
        _require_optional_timezone_aware(self.completed_at, "completed_at")
