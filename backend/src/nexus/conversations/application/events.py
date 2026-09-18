"""Provider-independent Conversation streaming events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from nexus.conversations.domain import GenerationFinishReason


class ConversationEventType(StrEnum):
    GENERATION_STARTED = "generation.started"
    MESSAGE_DELTA = "message.delta"
    GENERATION_USAGE = "generation.usage"
    GENERATION_COMPLETED = "generation.completed"
    GENERATION_ERROR = "generation.error"


@dataclass(frozen=True)
class GenerationStarted:
    conversation_public_id: UUID
    generation_public_id: UUID
    model: str
    type: ConversationEventType = ConversationEventType.GENERATION_STARTED


@dataclass(frozen=True)
class MessageDelta:
    conversation_public_id: UUID
    generation_public_id: UUID
    delta: str
    type: ConversationEventType = ConversationEventType.MESSAGE_DELTA


@dataclass(frozen=True)
class GenerationUsage:
    generation_public_id: UUID
    input_tokens: int
    output_tokens: int
    total_tokens: int
    type: ConversationEventType = ConversationEventType.GENERATION_USAGE


@dataclass(frozen=True)
class GenerationCompleted:
    conversation_public_id: UUID
    generation_public_id: UUID
    assistant_message_public_id: UUID
    finish_reason: GenerationFinishReason
    type: ConversationEventType = ConversationEventType.GENERATION_COMPLETED


@dataclass(frozen=True)
class GenerationError:
    generation_public_id: UUID
    kind: str
    message: str
    type: ConversationEventType = ConversationEventType.GENERATION_ERROR


ConversationEvent = (
    GenerationStarted
    | MessageDelta
    | GenerationUsage
    | GenerationCompleted
    | GenerationError
)

__all__ = [
    "ConversationEvent",
    "ConversationEventType",
    "GenerationCompleted",
    "GenerationError",
    "GenerationStarted",
    "GenerationUsage",
    "MessageDelta",
]
