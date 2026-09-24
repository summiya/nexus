from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.conversations.application.events import (
    GenerationCompleted,
    GenerationError,
    GenerationStarted,
    MessageDelta,
)
from nexus.conversations.application.stream_events import ConversationEventAssembler
from nexus.conversations.application.stream_lifecycle import ConversationStreamLifecycle
from nexus.conversations.application.stream_message import (
    StreamConversationMessage,
    StreamConversationMessageRequest,
)
from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    GenerationStatus,
)
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.persistence import _conversation_queries as queries
from nexus.infrastructure.persistence.conversation import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.models.generation import (
    Generation as GenerationModel,
)
from nexus.infrastructure.persistence.models.message import Message as MessageModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.llm.application import ModelPolicy
from nexus.llm.domain import (
    LLMCompletedEvent,
    LLMEvent,
    LLMRequest,
    LLMResponse,
    LLMStartedEvent,
    LLMTextDeltaEvent,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


class EventIterator:
    def __init__(
        self,
        events: list[LLMEvent],
        *,
        before_next: Callable[[], None] | None = None,
    ) -> None:
        self.events = events
        self.before_next = before_next
        self.index = 0
        self.close_count = 0

    def __aiter__(self) -> EventIterator:
        return self

    async def __anext__(self) -> LLMEvent:
        if self.before_next is not None:
            self.before_next()
        if self.index >= len(self.events):
            raise StopAsyncIteration
        event = self.events[self.index]
        self.index += 1
        return event

    async def aclose(self) -> None:
        self.close_count += 1


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


class TestGateway:
    __test__ = False

    def __init__(self, iterator: AsyncIterator[LLMEvent]) -> None:
        self.iterator = iterator
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise NotImplementedError

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        return self.iterator


@pytest.fixture
def migrated_lifecycle_engine(
    migrated_database: tuple[Config, Engine],
) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def _seed_conversation(
    engine: Engine,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, Conversation]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Stream lifecycle organization",
            slug=f"stream-lifecycle-{uuid4().hex[:12]}",
            status="active",
        )
        session.add(
            User(
                public_id=user_public_id,
                organization=organization,
                email=f"{uuid4().hex}@example.com",
                status="active",
            )
        )
        session.commit()

    conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=user_public_id,
        title="Lifecycle conversation",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    asyncio.run(
        SqlAlchemyConversationPersistence(session_factory).create_conversation(
            conversation
        )
    )
    return organization_public_id, user_public_id, conversation


def _service(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: TestGateway,
) -> StreamConversationMessage:
    return StreamConversationMessage(
        persistence=SqlAlchemyConversationPersistence(session_factory),
        llm_gateway=gateway,
        model_policy=ModelPolicy.from_models(["gpt-test"]),
        history_limit=10,
        history_max_chars=1_000,
        message_max_length=100,
    )


def _request(
    organization_public_id: UUID,
    user_public_id: UUID,
    conversation: Conversation,
    *,
    content: str = "Generate a response",
    idempotency_key: UUID | None = None,
) -> StreamConversationMessageRequest:
    return StreamConversationMessageRequest(
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
        conversation_public_id=conversation.public_id,
        content=content,
        model="gpt-test",
        idempotency_key=idempotency_key,
    )


def _assert_terminal_state(
    engine: Engine,
    *,
    generation_public_id: UUID,
    expected_status: GenerationStatus,
    expected_error_kind: str | None = None,
    assistant_count: int,
) -> None:
    with Session(engine) as session:
        generation = session.scalar(
            select(GenerationModel).where(
                GenerationModel.public_id == generation_public_id
            )
        )
        assert generation is not None
        assert generation.status == expected_status.value
        assert generation.error_kind == expected_error_kind
        assert (generation.assistant_message_id is not None) is (assistant_count == 1)
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.conversation_id == generation.conversation_id,
                    MessageModel.role == ConversationMessageRole.ASSISTANT.value,
                )
            )
            == assistant_count
        )


def test_concurrent_messages_to_one_conversation_accept_exactly_one_request(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    gateways = [
        TestGateway(EventIterator([LLMStartedEvent()])),
        TestGateway(EventIterator([LLMStartedEvent()])),
    ]
    services = [
        _service(conversation_async_session_factory, gateway) for gateway in gateways
    ]
    barrier = asyncio.Barrier(2)
    original_insert = queries.insert_generation

    async def race_generation_insert(*args: object, **kwargs: object) -> None:
        await asyncio.wait_for(barrier.wait(), timeout=5)
        await original_insert(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(queries, "insert_generation", race_generation_insert)

    async def attempt(
        service: StreamConversationMessage,
        content: str,
    ) -> ConversationStreamLifecycle | NexusError:
        try:
            return await service.prepare(
                _request(
                    organization_id,
                    user_id,
                    conversation,
                    content=content,
                )
            )
        except NexusError as exc:
            return exc

    async def run() -> tuple[ConversationStreamLifecycle, NexusError]:
        results = await asyncio.gather(
            attempt(services[0], "first concurrent request"),
            attempt(services[1], "second concurrent request"),
        )
        prepared = [
            result
            for result in results
            if isinstance(result, ConversationStreamLifecycle)
        ]
        conflicts = [result for result in results if isinstance(result, NexusError)]
        assert len(prepared) == 1
        assert len(conflicts) == 1
        return prepared[0], conflicts[0]

    prepared, conflict = asyncio.run(run())

    assert conflict.code is ErrorCode.CONFLICT
    assert sum(len(gateway.requests) for gateway in gateways) == 1
    with Session(migrated_lifecycle_engine) as session:
        assert session.scalar(select(func.count(GenerationModel.id))) == 1
        assert (
            session.scalar(
                select(func.count(GenerationModel.id)).where(
                    GenerationModel.status == GenerationStatus.RUNNING.value
                )
            )
            == 1
        )
        assert session.scalar(select(func.count(MessageModel.id))) == 1

    asyncio.run(prepared.aclose())


def test_different_conversations_run_concurrently_and_may_reuse_idempotency_key(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id, user_id, first_conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    second_conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=organization_id,
        created_by_user_public_id=user_id,
        title="Second lifecycle conversation",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    persistence = SqlAlchemyConversationPersistence(conversation_async_session_factory)
    asyncio.run(persistence.create_conversation(second_conversation))
    gateways = [
        TestGateway(EventIterator([LLMStartedEvent()])),
        TestGateway(EventIterator([LLMStartedEvent()])),
    ]
    services = [
        _service(conversation_async_session_factory, gateway) for gateway in gateways
    ]
    idempotency_key = uuid4()
    barrier = asyncio.Barrier(2)
    original_insert = queries.insert_generation

    async def race_generation_insert(*args: object, **kwargs: object) -> None:
        await asyncio.wait_for(barrier.wait(), timeout=5)
        await original_insert(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(queries, "insert_generation", race_generation_insert)

    async def run() -> tuple[
        ConversationStreamLifecycle,
        ConversationStreamLifecycle,
    ]:
        first, second = await asyncio.gather(
            services[0].prepare(
                _request(
                    organization_id,
                    user_id,
                    first_conversation,
                    idempotency_key=idempotency_key,
                )
            ),
            services[1].prepare(
                _request(
                    organization_id,
                    user_id,
                    second_conversation,
                    idempotency_key=idempotency_key,
                )
            ),
        )
        return first, second

    prepared = asyncio.run(run())

    assert sum(len(gateway.requests) for gateway in gateways) == 2
    with Session(migrated_lifecycle_engine) as session:
        assert (
            session.scalar(
                select(func.count(GenerationModel.id)).where(
                    GenerationModel.status == GenerationStatus.RUNNING.value
                )
            )
            == 2
        )
        assert session.scalar(select(func.count(MessageModel.id))) == 2

    async def close() -> None:
        await asyncio.gather(*(stream.aclose() for stream in prepared))

    asyncio.run(close())


def test_completed_idempotent_request_is_not_submitted_again(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    idempotency_key = uuid4()
    first_gateway = TestGateway(
        EventIterator(
            [
                LLMStartedEvent(),
                LLMTextDeltaEvent(delta="completed response"),
                LLMCompletedEvent(),
            ]
        )
    )
    first_service = _service(conversation_async_session_factory, first_gateway)

    async def complete_first_request() -> None:
        prepared = await first_service.prepare(
            _request(
                organization_id,
                user_id,
                conversation,
                idempotency_key=idempotency_key,
            )
        )
        events = [event async for event in prepared]
        assert isinstance(events[-1], GenerationCompleted)

    asyncio.run(complete_first_request())

    with Session(migrated_lifecycle_engine) as session:
        original_message_count = session.scalar(select(func.count(MessageModel.id)))
        original_generation_count = session.scalar(
            select(func.count(GenerationModel.id))
        )

    retry_gateway = TestGateway(EventIterator([LLMStartedEvent()]))
    retry_service = _service(conversation_async_session_factory, retry_gateway)
    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            retry_service.prepare(
                _request(
                    organization_id,
                    user_id,
                    conversation,
                    content="retry must not be persisted",
                    idempotency_key=idempotency_key,
                )
            )
        )

    assert exc_info.value.code is ErrorCode.CONFLICT
    assert exc_info.value.message == "This message request has already been accepted."
    assert retry_gateway.requests == []
    with Session(migrated_lifecycle_engine) as session:
        assert session.scalar(select(func.count(MessageModel.id))) == (
            original_message_count
        )
        assert session.scalar(select(func.count(GenerationModel.id))) == (
            original_generation_count
        )


def test_successful_stream_closes_database_sessions_before_provider_waits(
    migrated_lifecycle_engine: Engine,
    conversation_async_engine: AsyncEngine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    active_connections = 0

    def track_checkout(*_args: object) -> None:
        nonlocal active_connections
        active_connections += 1

    def track_checkin(*_args: object) -> None:
        nonlocal active_connections
        active_connections -= 1

    event.listen(conversation_async_engine.sync_engine, "checkout", track_checkout)
    event.listen(conversation_async_engine.sync_engine, "checkin", track_checkin)

    def assert_no_active_session() -> None:
        assert active_connections == 0

    iterator = EventIterator(
        [
            LLMStartedEvent(),
            LLMTextDeltaEvent(delta="completed response"),
            LLMCompletedEvent(),
        ],
        before_next=assert_no_active_session,
    )
    gateway = TestGateway(iterator)
    service = _service(conversation_async_session_factory, gateway)

    async def run() -> tuple[UUID, list[object]]:
        prepared = await service.prepare(
            _request(organization_id, user_id, conversation)
        )
        events = [event async for event in prepared]
        return prepared.generation.public_id, events

    try:
        generation_id, events = asyncio.run(run())
    finally:
        event.remove(conversation_async_engine.sync_engine, "checkout", track_checkout)
        event.remove(conversation_async_engine.sync_engine, "checkin", track_checkin)

    assert isinstance(events[-1], GenerationCompleted)
    assert iterator.close_count == 1
    _assert_terminal_state(
        migrated_lifecycle_engine,
        generation_public_id=generation_id,
        expected_status=GenerationStatus.COMPLETED,
        assistant_count=1,
    )


def test_early_close_persists_cancelled_without_assistant(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    iterator = EventIterator([LLMStartedEvent(), LLMTextDeltaEvent(delta="partial")])
    service = _service(conversation_async_session_factory, TestGateway(iterator))

    async def run() -> UUID:
        prepared = await service.prepare(
            _request(organization_id, user_id, conversation)
        )
        stream = prepared.__aiter__()
        assert isinstance(await anext(stream), GenerationStarted)
        assert isinstance(await anext(stream), MessageDelta)
        await stream.aclose()
        await prepared.aclose()
        return prepared.generation.public_id

    generation_id = asyncio.run(run())

    assert iterator.close_count == 1
    _assert_terminal_state(
        migrated_lifecycle_engine,
        generation_public_id=generation_id,
        expected_status=GenerationStatus.CANCELLED,
        assistant_count=0,
    )


@pytest.mark.parametrize("phase", ["preflight", "active"])
def test_request_cancellation_persists_cancelled_without_assistant(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    phase: str,
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    iterator = BlockingIterator(
        first_event=LLMStartedEvent() if phase == "active" else None
    )
    service = _service(conversation_async_session_factory, TestGateway(iterator))
    generation_id: UUID | None = None

    async def run() -> None:
        nonlocal generation_id
        if phase == "preflight":
            task = asyncio.create_task(
                service.prepare(_request(organization_id, user_id, conversation))
            )
        else:
            prepared = await service.prepare(
                _request(organization_id, user_id, conversation)
            )
            generation_id = prepared.generation.public_id

            async def consume() -> None:
                async for _event in prepared:
                    pass

            task = asyncio.create_task(consume())

        await iterator.waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    if generation_id is None:
        with Session(migrated_lifecycle_engine) as session:
            generation_id = session.scalar(select(GenerationModel.public_id))
    assert generation_id is not None
    assert iterator.close_count == 1
    _assert_terminal_state(
        migrated_lifecycle_engine,
        generation_public_id=generation_id,
        expected_status=GenerationStatus.CANCELLED,
        assistant_count=0,
    )


def test_incomplete_provider_stream_persists_failed_without_assistant(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    iterator = EventIterator([LLMStartedEvent(), LLMTextDeltaEvent(delta="partial")])
    service = _service(conversation_async_session_factory, TestGateway(iterator))

    async def run() -> tuple[UUID, list[object]]:
        prepared = await service.prepare(
            _request(organization_id, user_id, conversation)
        )
        events = [event async for event in prepared]
        return prepared.generation.public_id, events

    generation_id, events = asyncio.run(run())

    assert isinstance(events[-1], GenerationError)
    assert events[-1].kind == "incomplete_provider_stream"
    _assert_terminal_state(
        migrated_lifecycle_engine,
        generation_public_id=generation_id,
        expected_status=GenerationStatus.FAILED,
        expected_error_kind="incomplete_provider_stream",
        assistant_count=0,
    )


def test_unexpected_processing_error_persists_stable_failure_without_assistant(
    migrated_lifecycle_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    iterator = EventIterator(
        [
            LLMStartedEvent(),
            LLMTextDeltaEvent(delta="partial"),
            LLMCompletedEvent(),
        ]
    )
    service = _service(conversation_async_session_factory, TestGateway(iterator))
    original = ConversationEventAssembler.process

    def fail_processing(
        assembler: ConversationEventAssembler,
        event: LLMEvent,
    ) -> object:
        if isinstance(event, LLMTextDeltaEvent):
            raise TypeError("internal mapping detail")
        return original(assembler, event)

    monkeypatch.setattr(ConversationEventAssembler, "process", fail_processing)

    async def run() -> tuple[UUID, list[object]]:
        prepared = await service.prepare(
            _request(organization_id, user_id, conversation)
        )
        events = [event async for event in prepared]
        return prepared.generation.public_id, events

    generation_id, events = asyncio.run(run())

    assert isinstance(events[-1], GenerationError)
    assert events[-1].kind == "stream_processing_failure"
    assert events[-1].message == "The generation could not be completed."
    _assert_terminal_state(
        migrated_lifecycle_engine,
        generation_public_id=generation_id,
        expected_status=GenerationStatus.FAILED,
        expected_error_kind="stream_processing_failure",
        assistant_count=0,
    )


def test_prepare_cancellation_waits_for_transaction_commit_then_cancels_generation(
    migrated_lifecycle_engine: Engine,
    conversation_async_engine: AsyncEngine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id, user_id, conversation = _seed_conversation(
        migrated_lifecycle_engine, conversation_async_session_factory
    )
    iterator = EventIterator([LLMStartedEvent()])
    gateway = TestGateway(iterator)
    service = _service(conversation_async_session_factory, gateway)
    transaction_ready = asyncio.Event()
    release_transaction = asyncio.Event()
    original_history = queries.list_recent_messages
    active_connections = 0

    def track_checkout(*_args: object) -> None:
        nonlocal active_connections
        active_connections += 1

    def track_checkin(*_args: object) -> None:
        nonlocal active_connections
        active_connections -= 1

    event.listen(conversation_async_engine.sync_engine, "checkout", track_checkout)
    event.listen(conversation_async_engine.sync_engine, "checkin", track_checkin)

    async def block_before_commit(*args: object, **kwargs: object) -> list[Any]:
        history = await original_history(*args, **kwargs)  # type: ignore[arg-type]
        transaction_ready.set()
        await asyncio.wait_for(release_transaction.wait(), timeout=5)
        return history

    monkeypatch.setattr(queries, "list_recent_messages", block_before_commit)

    async def run() -> None:
        task = asyncio.create_task(
            service.prepare(_request(organization_id, user_id, conversation))
        )
        await asyncio.wait_for(transaction_ready.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_transaction.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(run())
    finally:
        event.remove(conversation_async_engine.sync_engine, "checkout", track_checkout)
        event.remove(conversation_async_engine.sync_engine, "checkin", track_checkin)

    assert gateway.requests == []
    assert active_connections == 0
    with Session(migrated_lifecycle_engine) as session:
        generation_id = session.scalar(select(GenerationModel.public_id))
    assert generation_id is not None
    _assert_terminal_state(
        migrated_lifecycle_engine,
        generation_public_id=generation_id,
        expected_status=GenerationStatus.CANCELLED,
        assistant_count=0,
    )
