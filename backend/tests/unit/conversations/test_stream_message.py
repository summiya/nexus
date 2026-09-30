from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.conversations.application import stream_lifecycle as stream_lifecycle_module
from nexus.conversations.application.events import (
    GenerationCompleted,
    GenerationError,
    GenerationStarted,
    GenerationUsage,
    MessageDelta,
)
from nexus.conversations.application.stream_events import ConversationEventAssembler
from nexus.conversations.application.stream_message import (
    StreamConversationMessage,
    StreamConversationMessageRequest,
)
from nexus.conversations.domain import Conversation, Generation, Message
from nexus.conversations.ports.persistence import (
    ConversationGenerationInProgressError,
    ConversationRequestAlreadySubmittedError,
)
from nexus.errors import ErrorCode, NexusError
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
from nexus.model_providers.domain import ConfiguredModelId

ORG_ID = uuid4()
USER_ID = uuid4()
CONVERSATION_ID = uuid4()
NOW = datetime(2026, 1, 1, tzinfo=UTC)
MODEL_ID = ConfiguredModelId(uuid4())


@dataclass(frozen=True)
class FakeResolvedModel:
    model_id: ConfiguredModelId = MODEL_ID


class FakeResolver:
    def __init__(self, error: NexusError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[UUID, ConfiguredModelId | None]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        model_id: ConfiguredModelId | None,
    ) -> FakeResolvedModel:
        self.calls.append((organization_public_id, model_id))
        if self.error is not None:
            raise self.error
        return FakeResolvedModel()


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
        self.initial_titles: list[str | None] = []
        self.completed: list[tuple[Message, Generation]] = []
        self.failed: list[Generation] = []
        self.cancelled: list[Generation] = []

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
    ) -> tuple[Message, ...]:
        assert organization_public_id == ORG_ID
        assert conversation.public_id == CONVERSATION_ID
        assert history_limit == 10
        self.initial_titles.append(initial_title)
        self.prepared.append((message, generation))
        return (message,)

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> bool:
        assert organization_public_id == ORG_ID
        self.completed.append((assistant_message, generation))
        return True

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool:
        assert organization_public_id == ORG_ID
        self.failed.append(generation)
        return True

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool:
        assert organization_public_id == ORG_ID
        self.cancelled.append(generation)
        return True


class FakeGateway:
    def __init__(self, events: list[LLMEvent] | None = None) -> None:
        self.events = events or [
            LLMStartedEvent(),
            LLMTextDeltaEvent(delta="Hello"),
            LLMCompletedEvent(),
            LLMUsageEvent(usage=LLMUsage(1, 2, 3)),
        ]
        self.requests: list[LLMRequest] = []
        self.targets: list[FakeResolvedModel] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise NotImplementedError

    def stream(
        self,
        *,
        request: LLMRequest,
        target: FakeResolvedModel,
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        self.targets.append(target)

        async def events() -> AsyncIterator[LLMEvent]:
            for event in self.events:
                yield event

        return events()


class CancellationIterator:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> CancellationIterator:
        return self

    async def __anext__(self) -> LLMEvent:
        raise asyncio.CancelledError

    async def aclose(self) -> None:
        self.closed = True


class CancellationGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.iterator = CancellationIterator()

    def stream(
        self,
        *,
        request: LLMRequest,
        target: FakeResolvedModel,
    ) -> AsyncIterator[LLMEvent]:
        del request, target
        return self.iterator


class TrackingIterator:
    def __init__(
        self,
        events: list[LLMEvent],
        *,
        close_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.close_error = close_error
        self.index = 0
        self.close_count = 0

    def __aiter__(self) -> TrackingIterator:
        return self

    async def __anext__(self) -> LLMEvent:
        if self.index >= len(self.events):
            raise StopAsyncIteration
        event = self.events[self.index]
        self.index += 1
        return event

    async def aclose(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class TrackingGateway(FakeGateway):
    def __init__(self, iterator: TrackingIterator) -> None:
        super().__init__()
        self.iterator = iterator

    def stream(
        self,
        *,
        request: LLMRequest,
        target: FakeResolvedModel,
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        self.targets.append(target)
        return self.iterator


class BlockingIterator:
    def __init__(self, first_event: LLMEvent | None = None) -> None:
        self.first_event = first_event
        self.first_event_returned = False
        self.waiting = asyncio.Event()
        self.close_count = 0

    def __aiter__(self) -> BlockingIterator:
        return self

    async def __anext__(self) -> LLMEvent:
        if self.first_event is not None and not self.first_event_returned:
            self.first_event_returned = True
            return self.first_event
        self.waiting.set()
        await asyncio.Event().wait()
        raise AssertionError("the blocked provider should be cancelled")

    async def aclose(self) -> None:
        self.close_count += 1


def make_request(
    *,
    idempotency_key: UUID | None = None,
) -> StreamConversationMessageRequest:
    return StreamConversationMessageRequest(
        organization_public_id=ORG_ID,
        user_public_id=USER_ID,
        conversation_public_id=CONVERSATION_ID,
        content="  hello  ",
        model_id=None,
        idempotency_key=idempotency_key,
    )


@pytest.mark.parametrize(
    ("persistence_error", "message"),
    [
        (
            ConversationGenerationInProgressError("active"),
            "A generation is already in progress for this conversation.",
        ),
        (
            ConversationRequestAlreadySubmittedError("duplicate"),
            "This message request has already been accepted.",
        ),
    ],
)
def test_preparation_conflicts_are_safe_and_do_not_invoke_provider(
    persistence_error: Exception,
    message: str,
) -> None:
    class ConflictingPersistence(FakePersistence):
        async def prepare_generation(
            self,
            *,
            organization_public_id: UUID,
            conversation: Conversation,
            message: Message,
            generation: Generation,
            history_limit: int,
            initial_title: str | None = None,
        ) -> tuple[Message, ...]:
            del (
                organization_public_id,
                conversation,
                message,
                generation,
                history_limit,
                initial_title,
            )
            raise persistence_error

    gateway = FakeGateway()
    service = StreamConversationMessage(
        persistence=ConflictingPersistence(),
        runtime_chat_gateway=gateway,
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(service.prepare(make_request(idempotency_key=uuid4())))

    assert exc_info.value.code is ErrorCode.CONFLICT
    assert exc_info.value.message == message
    assert gateway.requests == []


def test_stream_preflights_before_returning_and_finalizes_after_exhaustion() -> None:
    persistence = FakePersistence()
    gateway = FakeGateway()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
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


def test_resolves_explicit_model_once_and_passes_same_snapshot_to_runtime() -> None:
    persistence = FakePersistence()
    resolver = FakeResolver()
    gateway = FakeGateway()
    selected_model_id = ConfiguredModelId(uuid4())
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=resolver,
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(
            replace(make_request(), model_id=selected_model_id)
        )
        await prepared.aclose()

    asyncio.run(run())

    assert resolver.calls == [(ORG_ID, selected_model_id)]
    assert len(gateway.targets) == 1
    assert gateway.targets[0].model_id == MODEL_ID
    assert persistence.prepared[0][1].configured_model_public_id == MODEL_ID.value
    assert gateway.requests[0].model == "configured-chat-model"


def test_derives_initial_title_from_first_user_message() -> None:
    persistence = FakePersistence()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=FakeGateway(),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=500,
    )
    request = replace(
        make_request(),
        content="  Explain   message queues\nand Kafka for a beginner  ",
    )

    async def run() -> None:
        prepared = await service.prepare(request)
        await prepared.aclose()

    asyncio.run(run())

    assert persistence.initial_titles == ["Explain message queues and Kafka for a beginner"]


def test_truncates_generated_conversation_title() -> None:
    persistence = FakePersistence()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=FakeGateway(),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=500,
    )
    request = replace(make_request(), content="x" * 120)

    async def run() -> None:
        prepared = await service.prepare(request)
        await prepared.aclose()

    asyncio.run(run())

    assert persistence.initial_titles == [("x" * 79) + "…"]


def test_preserves_an_existing_conversation_title() -> None:
    persistence = FakePersistence()
    persistence.conversation = replace(
        persistence.conversation,
        title="Existing title",
    )
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=FakeGateway(),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(make_request())
        await prepared.aclose()

    asyncio.run(run())

    assert persistence.initial_titles == [None]


def test_generation_preparation_finishes_before_provider_streaming_starts() -> None:
    timeline: list[str] = []

    class OrderedPersistence(FakePersistence):
        async def prepare_generation(
            self,
            *,
            organization_public_id: UUID,
            conversation: Conversation,
            message: Message,
            generation: Generation,
            history_limit: int,
            initial_title: str | None = None,
        ) -> tuple[Message, ...]:
            prepared = await super().prepare_generation(
                organization_public_id=organization_public_id,
                conversation=conversation,
                message=message,
                generation=generation,
                history_limit=history_limit,
                initial_title=initial_title,
            )
            timeline.append("persistence_prepared")
            return prepared

    class OrderedGateway(FakeGateway):
        def stream(
            self,
            *,
            request: LLMRequest,
            target: FakeResolvedModel,
        ) -> AsyncIterator[LLMEvent]:
            timeline.append("provider_stream_started")
            return super().stream(request=request, target=target)

    service = StreamConversationMessage(
        persistence=OrderedPersistence(),
        runtime_chat_gateway=OrderedGateway(),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(make_request())
        await prepared.aclose()

    asyncio.run(run())

    assert timeline == ["persistence_prepared", "provider_stream_started"]


def test_early_close_cancels_generation_and_closes_provider_once() -> None:
    persistence = FakePersistence()
    iterator = TrackingIterator([LLMStartedEvent(), LLMTextDeltaEvent(delta="partial")])
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(make_request())
        stream = prepared.__aiter__()
        assert isinstance(await anext(stream), GenerationStarted)
        assert isinstance(await anext(stream), MessageDelta)
        await stream.aclose()
        await prepared.aclose()

    asyncio.run(run())

    assert iterator.close_count == 1
    assert len(persistence.cancelled) == 1
    assert persistence.failed == []
    assert persistence.completed == []


def test_provider_eof_without_completion_fails_generation() -> None:
    persistence = FakePersistence()
    iterator = TrackingIterator([LLMStartedEvent(), LLMTextDeltaEvent(delta="partial")])
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> list[object]:
        return [event async for event in await service.prepare(make_request())]

    events = asyncio.run(run())

    assert isinstance(events[-1], GenerationError)
    assert events[-1].kind == "incomplete_provider_stream"
    assert iterator.close_count == 1
    assert persistence.failed[0].error_kind == "incomplete_provider_stream"
    assert persistence.cancelled == []
    assert persistence.completed == []


def test_stream_does_not_emit_completion_when_database_transition_loses() -> None:
    class LosingCompletionPersistence(FakePersistence):
        async def complete_generation(
            self,
            *,
            organization_public_id: UUID,
            assistant_message: Message,
            generation: Generation,
        ) -> bool:
            assert organization_public_id == ORG_ID
            self.completed.append((assistant_message, generation))
            return False

    persistence = LosingCompletionPersistence()
    iterator = TrackingIterator(
        [
            LLMStartedEvent(),
            LLMTextDeltaEvent(delta="response"),
            LLMCompletedEvent(),
        ]
    )
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> list[object]:
        return [event async for event in await service.prepare(make_request())]

    events = asyncio.run(run())

    assert not any(isinstance(event, GenerationCompleted) for event in events)
    assert not any(isinstance(event, GenerationError) for event in events)
    assert iterator.close_count == 1
    assert len(persistence.completed) == 1
    assert persistence.failed == []
    assert persistence.cancelled == []


def test_completion_persistence_failure_emits_safe_failure_and_closes_provider() -> (
    None
):
    class FailingCompletionPersistence(FakePersistence):
        def __init__(self) -> None:
            super().__init__()
            self.completion_attempts: list[tuple[Message, Generation]] = []

        async def complete_generation(
            self,
            *,
            organization_public_id: UUID,
            assistant_message: Message,
            generation: Generation,
        ) -> bool:
            assert organization_public_id == ORG_ID
            self.completion_attempts.append((assistant_message, generation))
            raise RuntimeError("database unavailable")

    persistence = FailingCompletionPersistence()
    provider_events: list[LLMEvent] = [
        LLMStartedEvent(),
        LLMTextDeltaEvent(delta="response"),
        LLMCompletedEvent(),
    ]
    iterator = TrackingIterator(provider_events)
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> list[object]:
        return [event async for event in await service.prepare(make_request())]

    events = asyncio.run(run())

    assert iterator.index == len(provider_events)
    assert len(persistence.completion_attempts) == 1
    assert not any(isinstance(event, GenerationCompleted) for event in events)
    assert isinstance(events[-1], GenerationError)
    assert events[-1].kind == "persistence_failure"
    assert events[-1].message == "The generation could not be completed."
    assert len(persistence.failed) == 1
    assert persistence.failed[0].error_kind == "persistence_failure"
    assert persistence.cancelled == []
    assert iterator.close_count == 1


def test_unexpected_processing_error_is_logged_and_persisted_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persistence = FakePersistence()
    iterator = TrackingIterator(
        [
            LLMStartedEvent(),
            LLMTextDeltaEvent(delta="partial"),
            LLMCompletedEvent(),
        ]
    )
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )
    original = ConversationEventAssembler.process
    logged: list[tuple[str, BaseException | None]] = []

    def fail_processing(
        assembler: ConversationEventAssembler,
        event: LLMEvent,
    ) -> object:
        if isinstance(event, LLMTextDeltaEvent):
            raise TypeError("event mapper exploded")
        return original(assembler, event)

    monkeypatch.setattr(ConversationEventAssembler, "process", fail_processing)
    monkeypatch.setattr(
        stream_lifecycle_module.logger,
        "exception",
        lambda event, **_context: logged.append((event, sys.exception())),
    )

    async def run() -> list[object]:
        return [event async for event in await service.prepare(make_request())]

    events = asyncio.run(run())

    assert isinstance(events[-1], GenerationError)
    assert events[-1].kind == "stream_processing_failure"
    assert persistence.failed[0].error_kind == "stream_processing_failure"
    assert persistence.cancelled == []
    assert persistence.completed == []
    assert logged[0][0] == "conversation_stream_processing_failed"
    assert isinstance(logged[0][1], TypeError)
    assert str(logged[0][1]) == "event mapper exploded"


def test_cleanup_failure_does_not_prevent_cancellation_or_repeat_close() -> None:
    persistence = FakePersistence()
    iterator = TrackingIterator(
        [LLMStartedEvent(), LLMTextDeltaEvent(delta="partial")],
        close_error=RuntimeError("cleanup failed"),
    )
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(make_request())
        await prepared.aclose()
        await prepared.aclose()

    asyncio.run(run())

    assert iterator.close_count == 1
    assert len(persistence.cancelled) == 1
    assert persistence.failed == []
    assert persistence.completed == []


def test_provider_failure_before_first_event_becomes_http_error_and_fails_generation() -> (
    None
):
    class FailingGateway(FakeGateway):
        def stream(
            self,
            *,
            request: LLMRequest,
            target: FakeResolvedModel,
        ) -> AsyncIterator[LLMEvent]:
            del request, target

            async def events() -> AsyncIterator[LLMEvent]:
                raise LLMProviderUnavailableError("provider detail")
                yield LLMStartedEvent()

            return events()

    persistence = FakePersistence()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=FailingGateway(),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        await service.prepare(make_request())

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert persistence.failed[0].error_kind == "provider_unavailable"


def test_preflight_cancellation_closes_provider_and_persists_cancelled_generation() -> (
    None
):
    persistence = FakePersistence()
    gateway = CancellationGateway()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        await service.prepare(make_request())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())

    assert gateway.iterator.closed is True
    assert len(persistence.cancelled) == 1
    assert persistence.failed == []
    assert persistence.completed == []


def test_request_task_cancellation_during_preflight_is_not_processing_failure() -> None:
    persistence = FakePersistence()
    iterator = BlockingIterator()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        task = asyncio.create_task(service.prepare(make_request()))
        await iterator.waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert iterator.close_count == 1
    assert len(persistence.cancelled) == 1
    assert persistence.failed == []
    assert persistence.completed == []


def test_request_task_cancellation_during_active_stream_is_not_processing_failure() -> (
    None
):
    persistence = FakePersistence()
    iterator = BlockingIterator(first_event=LLMStartedEvent())
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=TrackingGateway(iterator),
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(make_request())

        async def consume() -> None:
            async for _event in prepared:
                pass

        task = asyncio.create_task(consume())
        await iterator.waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert iterator.close_count == 1
    assert len(persistence.cancelled) == 1
    assert persistence.failed == []
    assert persistence.completed == []


def test_resolver_failure_does_not_persist_or_call_provider() -> None:
    persistence = FakePersistence()
    gateway = FakeGateway()
    resolver = FakeResolver(NexusError(ErrorCode.NOT_FOUND, "not found"))
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=resolver,
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )
    request = StreamConversationMessageRequest(
        organization_public_id=ORG_ID,
        user_public_id=USER_ID,
        conversation_public_id=CONVERSATION_ID,
        content="hello",
        model_id=ConfiguredModelId(uuid4()),
    )

    async def run() -> None:
        await service.prepare(request)

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert persistence.prepared == []
    assert gateway.requests == []


@pytest.mark.parametrize("content", ["   ", "x" * 101])
def test_rejects_invalid_content_before_loading_conversation(content: str) -> None:
    persistence = FakePersistence()
    gateway = FakeGateway()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )
    request = replace(make_request(), content=content)

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(service.prepare(request))

    assert exc_info.value.code is ErrorCode.VALIDATION_ERROR
    assert persistence.prepared == []
    assert gateway.requests == []


def test_hides_user_owned_conversation_from_another_user() -> None:
    persistence = FakePersistence()
    gateway = FakeGateway()
    resolver = FakeResolver()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=resolver,
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )
    request = replace(make_request(), user_public_id=uuid4())

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(service.prepare(request))

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert persistence.prepared == []
    assert gateway.requests == []
    assert resolver.calls == []


def test_rejects_workspace_conversation_until_workspace_authorization_exists() -> None:
    persistence = FakePersistence()
    persistence.conversation = replace(
        persistence.conversation,
        workspace_public_id=uuid4(),
    )
    gateway = FakeGateway()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(service.prepare(make_request()))

    assert exc_info.value.code is ErrorCode.FORBIDDEN
    assert persistence.prepared == []
    assert gateway.requests == []


def test_history_is_bounded_before_provider_invocation() -> None:
    class HistoryPersistence(FakePersistence):
        async def prepare_generation(
            self,
            *,
            organization_public_id: UUID,
            conversation: Conversation,
            message: Message,
            generation: Generation,
            history_limit: int,
            initial_title: str | None = None,
        ) -> tuple[Message, ...]:
            del organization_public_id, generation, history_limit, initial_title
            old = Message(
                public_id=uuid4(),
                conversation_public_id=conversation.public_id,
                role=message.role,
                content="123456",
                created_at=NOW,
            )
            recent = Message(
                public_id=uuid4(),
                conversation_public_id=conversation.public_id,
                role=message.role,
                content="abcd",
                created_at=NOW,
            )
            return old, recent, message

    persistence = HistoryPersistence()
    gateway = FakeGateway()
    service = StreamConversationMessage(
        persistence=persistence,
        runtime_chat_gateway=gateway,
        resolve_chat_model=FakeResolver(),
        history_limit=10,
        history_max_chars=9,
        message_max_length=100,
    )

    async def run() -> None:
        prepared = await service.prepare(make_request())
        await prepared.aclose()

    asyncio.run(run())

    assert [item.content for item in gateway.requests[0].messages] == ["abcd", "hello"]
