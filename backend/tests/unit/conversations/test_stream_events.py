from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.conversations.application.events import MessageDelta
from nexus.conversations.application.stream_events import (
    ConversationEventAssembler,
    ConversationStreamAssemblyError,
)
from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
)
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMErrorKind,
    LLMEvent,
    LLMFinishReason,
    LLMStartedEvent,
    LLMTextDeltaEvent,
    LLMToolCall,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMUsage,
    LLMUsageEvent,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _assembler() -> ConversationEventAssembler:
    conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
    )
    generation = Generation(
        public_id=uuid4(),
        conversation_public_id=conversation.public_id,
        user_message_public_id=uuid4(),
        model="gpt-test",
        status=GenerationStatus.RUNNING,
        started_at=NOW,
    )
    return ConversationEventAssembler(conversation, generation)


def test_assembles_text_usage_and_completion_records() -> None:
    assembler = _assembler()

    assert assembler.process(LLMStartedEvent()) is None
    delta = assembler.process(LLMTextDeltaEvent(delta="Hello"))
    assert isinstance(delta, MessageDelta)
    assert delta.delta == "Hello"
    assert assembler.process(LLMTextDeltaEvent(delta=" world")) is not None
    assert assembler.process(LLMUsageEvent(usage=LLMUsage(4, 2, 6))) is None
    assert (
        assembler.process(LLMCompletedEvent(finish_reason=LLMFinishReason.LENGTH))
        is None
    )

    assistant, generation = assembler.build_completion()
    usage = assembler.usage_event()

    assert assistant.role is ConversationMessageRole.ASSISTANT
    assert assistant.content == "Hello world"
    assert generation.status is GenerationStatus.COMPLETED
    assert generation.assistant_message_public_id == assistant.public_id
    assert generation.finish_reason is GenerationFinishReason.LENGTH
    assert (generation.input_tokens, generation.output_tokens) == (4, 2)
    assert generation.total_tokens == 6
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (4, 2, 6)


def test_incomplete_stream_cannot_build_completion() -> None:
    assembler = _assembler()
    assembler.process(LLMTextDeltaEvent(delta="partial"))

    with pytest.raises(
        ConversationStreamAssemblyError,
        match="incomplete_provider_stream",
    ) as exc_info:
        assembler.build_completion()

    assert exc_info.value.kind == "incomplete_provider_stream"


def test_completed_stream_requires_assistant_text() -> None:
    assembler = _assembler()
    assembler.process(LLMCompletedEvent())

    with pytest.raises(
        ConversationStreamAssemblyError,
        match="empty_assistant_response",
    ) as exc_info:
        assembler.build_completion()

    assert exc_info.value.kind == "empty_assistant_response"


def test_provider_error_preserves_stable_error_kind() -> None:
    assembler = _assembler()

    with pytest.raises(ConversationStreamAssemblyError) as exc_info:
        assembler.process(
            LLMErrorEvent(
                kind=LLMErrorKind.RATE_LIMITED,
                message="safe provider failure",
                retryable=True,
            )
        )

    assert exc_info.value.kind == "rate_limited"


@pytest.mark.parametrize(
    "event",
    [
        LLMToolCallStartedEvent(tool_call_id="call-1", name="search"),
        LLMToolCallDeltaEvent(tool_call_id="call-1", arguments_delta="{}"),
        LLMToolCallCompletedEvent(
            tool_call=LLMToolCall(id="call-1", name="search", arguments={})
        ),
    ],
)
def test_tool_call_events_are_rejected(event: LLMEvent) -> None:
    assembler = _assembler()

    with pytest.raises(ConversationStreamAssemblyError) as exc_info:
        assembler.process(event)

    assert exc_info.value.kind == "tool_calls_unsupported"
