from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.conversations.application.events import (
    GenerationCompleted,
    GenerationStarted,
    GenerationUsage,
    MessageDelta,
)
from nexus.conversations.application.stream_message import (
    StreamConversationMessage,
    StreamConversationMessageRequest,
)
from nexus.conversations.domain import Conversation, Generation, Message
from nexus.conversations.ports.persistence import PreparedGeneration
from nexus.errors import ErrorCode, NexusError
from nexus.llm.application import Stream
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMEvent,
    LLMMessage,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMStartedEvent,
    LLMTextDeltaEvent,
    LLMUsage,
    LLMUsageEvent,
)

ORG_ID = uuid4()
USER_ID = uuid4()
CONVERSATION_ID = uuid4()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakePersistence:
    def __init__(self) -> None:
        self.conversation = Conversation(
            public_id=CONVERSATION_ID,
            organization_public_id=ORG_ID,
            created_by_user_public_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
        self.prepared: list[tuple[Message, Generation]] = []
        self.completed: list[tuple[Message, Generation]] = []
        self.failed: list[Generation] = []

    async def create_conversation(self, conversation: Conversation) -> None:
        del conversation

    async def get_conversation(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        if (
            organization_public_id != ORG_ID
            or conversation_public_id != CONVERSATION_ID
        ):
            return None
        return self.conversation

    async def prepare_generation(
        self,
        *,
        organization_public_id: UUID,
        conversation: Conversation,
        message: Message,
        generation: Generation,
        history_limit: int,
    ) -> PreparedGeneration:
        assert organization_public_id == ORG_ID
        assert conversation.public_id == CONVERSATION_ID
        assert history_limit == 10
        self.prepared.append((message, generation))
        return PreparedGeneration(conversation, (message,))

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> None:
        assert organization_public_id == ORG_ID
        self.completed.append((assistant_message, generation))

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        assert organization_public_id == ORG_ID
        self.failed.append(generation)

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await self.fail_generation(
            organization_public_id=organization_public_id,
            generation=generation,
        )


class FakeGateway:
    def __init__(self, events: list[LLMEvent] | None = None) -> None:
        self.events = events or [
            LLMStartedEvent(),
            LLMTextDeltaEvent(delta="Hello"),
            LLMCompletedEvent(),
            LLMUsageEvent(usage=LLMUsage(1, 2, 3)),
        ]
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise NotImplementedError

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)

        async def events() -> AsyncIterator[LLMEvent]:
            for event in self.events:
                yield event

        return events()


def make_request() -> StreamConversationMessageRequest:
    return StreamConversationMessageRequest(
        organization_public_id=ORG_ID,
        user_public_id=USER_ID,
        conversation_public_id=CONVERSATION_ID,
        content="  hello  ",
        model=" gpt-test ",
    )


def test_stream_preflights_before_returning_and_finalizes_after_exhaustion() -> None:
    persistence = FakePersistence()
    gateway = FakeGateway()
    service = StreamConversationMessage(
        persistence=persistence,
        llm_stream=Stream(gateway=gateway),
        history_limit=10,
        message_max_length=100,
    )

    async def run() -> list[object]:
        prepared = await service.prepare(make_request())
        assert gateway.requests[0].messages[0] == LLMMessage(
            role=LLMRole.USER,
            content="hello",
        )
        return [event async for event in prepared]

    events = asyncio.run(run())

    assert [type(event) for event in events] == [
        GenerationStarted,
        MessageDelta,
        GenerationUsage,
        GenerationCompleted,
    ]
    assert len(persistence.prepared) == 1
    assert len(persistence.completed) == 1
    assert persistence.completed[0][0].content == "Hello"


def test_provider_failure_before_first_event_becomes_http_error_and_fails_generation() -> (
    None
):
    class FailingGateway(FakeGateway):
        def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
            del request

            async def events() -> AsyncIterator[LLMEvent]:
                raise LLMProviderUnavailableError("provider detail")
                yield LLMStartedEvent()

            return events()

    persistence = FakePersistence()
    service = StreamConversationMessage(
        persistence=persistence,
        llm_stream=Stream(gateway=FailingGateway()),
        history_limit=10,
        message_max_length=100,
    )

    async def run() -> None:
        await service.prepare(make_request())

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert persistence.failed[0].error_kind == "provider_unavailable"
