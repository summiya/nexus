"""Assemble provider-independent LLM events into Conversation output."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import uuid4

from nexus.conversations.application.events import (
    ConversationEvent,
    GenerationUsage,
    MessageDelta,
)
from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMEvent,
    LLMTextDeltaEvent,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMUsage,
    LLMUsageEvent,
)


class ConversationStreamAssemblyError(Exception):
    """A normalized provider stream cannot produce a valid Conversation result."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass
class ConversationEventAssembler:
    """Build Conversation events and terminal records from normalized LLM events."""

    conversation: Conversation
    generation: Generation
    _text_parts: list[str] = field(default_factory=list, init=False)
    _usage: LLMUsage | None = field(default=None, init=False)
    _finish_reason: GenerationFinishReason = field(
        default=GenerationFinishReason.UNKNOWN,
        init=False,
    )
    _provider_completed: bool = field(default=False, init=False)

    @property
    def finish_reason(self) -> GenerationFinishReason:
        return self._finish_reason

    def process(self, event: LLMEvent) -> ConversationEvent | None:
        if isinstance(event, LLMTextDeltaEvent):
            self._text_parts.append(event.delta)
            return MessageDelta(
                conversation_public_id=self.conversation.public_id,
                generation_public_id=self.generation.public_id,
                delta=event.delta,
            )
        if isinstance(event, LLMUsageEvent):
            self._usage = event.usage
            return None
        if isinstance(event, LLMCompletedEvent):
            self._finish_reason = _to_generation_finish_reason(event)
            self._provider_completed = True
            return None
        if isinstance(event, LLMErrorEvent):
            raise ConversationStreamAssemblyError(event.kind.value)
        if isinstance(
            event,
            (
                LLMToolCallStartedEvent,
                LLMToolCallDeltaEvent,
                LLMToolCallCompletedEvent,
            ),
        ):
            raise ConversationStreamAssemblyError("tool_calls_unsupported")
        return None

    def build_completion(self) -> tuple[Message, Generation]:
        if not self._provider_completed:
            raise ConversationStreamAssemblyError("incomplete_provider_stream")
        if not self._text_parts:
            raise ConversationStreamAssemblyError("empty_assistant_response")

        assistant_message = Message(
            public_id=uuid4(),
            conversation_public_id=self.conversation.public_id,
            role=ConversationMessageRole.ASSISTANT,
            content="".join(self._text_parts),
            created_at=datetime.now(UTC),
        )
        completed_generation = replace(
            self.generation,
            assistant_message_public_id=assistant_message.public_id,
            status=GenerationStatus.COMPLETED,
            finish_reason=self._finish_reason,
            input_tokens=self._usage.input_tokens if self._usage is not None else 0,
            output_tokens=self._usage.output_tokens if self._usage is not None else 0,
            total_tokens=self._usage.total_tokens if self._usage is not None else 0,
            completed_at=datetime.now(UTC),
            error_kind=None,
        )
        return assistant_message, completed_generation

    def usage_event(self) -> GenerationUsage | None:
        if self._usage is None:
            return None
        return GenerationUsage(
            generation_public_id=self.generation.public_id,
            input_tokens=self._usage.input_tokens,
            output_tokens=self._usage.output_tokens,
            total_tokens=self._usage.total_tokens,
        )


def _to_generation_finish_reason(
    event: LLMCompletedEvent,
) -> GenerationFinishReason:
    try:
        return GenerationFinishReason(event.finish_reason.value)
    except ValueError:
        return GenerationFinishReason.UNKNOWN
