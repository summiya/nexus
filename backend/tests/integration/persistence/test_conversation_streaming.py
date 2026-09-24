from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.persistence import ConversationReferenceError
from nexus.infrastructure.persistence import _conversation_queries as queries
from nexus.infrastructure.persistence.conversation import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.models.conversation import (
    Conversation as ConversationModel,
)
from nexus.infrastructure.persistence.models.generation import (
    Generation as GenerationModel,
)
from nexus.infrastructure.persistence.models.message import Message as MessageModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_identity(engine: Engine) -> tuple[UUID, UUID]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Streaming Organization",
            slug=f"streaming-{uuid4().hex[:12]}",
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
    return organization_public_id, user_public_id


def _seed_conversation(
    engine: Engine,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, Conversation]:
    organization_public_id, user_public_id = _seed_identity(engine)
    conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=user_public_id,
        title="Streaming conversation",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    asyncio.run(_persistence(session_factory).create_conversation(conversation))
    return organization_public_id, conversation


def _persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyConversationPersistence:
    return SqlAlchemyConversationPersistence(session_factory)


def _generation(conversation: Conversation) -> tuple[Message, Generation]:
    message = Message(
        public_id=uuid4(),
        conversation_public_id=conversation.public_id,
        role=ConversationMessageRole.USER,
        content="Generate a response",
        created_at=TIMESTAMP,
    )
    generation = Generation(
        public_id=uuid4(),
        conversation_public_id=conversation.public_id,
        user_message_public_id=message.public_id,
        model="gpt-test",
        status=GenerationStatus.RUNNING,
        started_at=TIMESTAMP,
    )
    return message, generation


@pytest.fixture
def migrated_streaming_engine(
    migrated_database: tuple[Config, Engine],
) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def test_create_and_get_conversation_preserve_tenant_scope(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_streaming_engine)
    conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=user_public_id,
        title="Public persistence boundary",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    persistence = _persistence(conversation_async_session_factory)

    asyncio.run(persistence.create_conversation(conversation))

    stored = asyncio.run(
        persistence.get_conversation(
            organization_public_id=organization_public_id,
            conversation_public_id=conversation.public_id,
        )
    )
    outside_tenant = asyncio.run(
        persistence.get_conversation(
            organization_public_id=uuid4(),
            conversation_public_id=conversation.public_id,
        )
    )

    assert stored == conversation
    assert outside_tenant is None


def test_create_conversation_rolls_back_an_invalid_creator(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, _user_public_id = _seed_identity(migrated_streaming_engine)
    conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=uuid4(),
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )

    with pytest.raises(ConversationReferenceError):
        asyncio.run(
            _persistence(conversation_async_session_factory).create_conversation(
                conversation
            )
        )

    with Session(migrated_streaming_engine) as session:
        assert (
            session.scalar(
                select(func.count(ConversationModel.id)).where(
                    ConversationModel.public_id == conversation.public_id
                )
            )
            == 0
        )


def test_prepare_generation_commits_running_user_message_and_generation(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    message, generation = _generation(conversation)

    prepared = asyncio.run(
        _persistence(conversation_async_session_factory).prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=10,
        )
    )

    assert prepared == (message,)
    with Session(migrated_streaming_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == message.public_id
                )
            )
            == 1
        )
        stored = session.scalar(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        )
        assert stored is not None
        assert stored.status == GenerationStatus.RUNNING.value


def test_prepare_generation_returns_limited_history_in_chronological_order(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    persistence = _persistence(conversation_async_session_factory)
    messages: list[Message] = []

    timestamps = (
        TIMESTAMP,
        TIMESTAMP + timedelta(seconds=1),
        TIMESTAMP + timedelta(seconds=1),
        TIMESTAMP + timedelta(seconds=1),
    )
    for created_at, content in zip(
        timestamps,
        ("first", "second", "third", "fourth"),
        strict=True,
    ):
        message = Message(
            public_id=uuid4(),
            conversation_public_id=conversation.public_id,
            role=ConversationMessageRole.USER,
            content=content,
            created_at=created_at,
        )
        generation = Generation(
            public_id=uuid4(),
            conversation_public_id=conversation.public_id,
            user_message_public_id=message.public_id,
            model="gpt-test",
            status=GenerationStatus.RUNNING,
            started_at=message.created_at,
        )
        prepared = asyncio.run(
            persistence.prepare_generation(
                organization_public_id=organization_public_id,
                conversation=conversation,
                message=message,
                generation=generation,
                history_limit=3,
            )
        )
        messages.append(message)
        if content != "fourth":
            asyncio.run(
                persistence.fail_generation(
                    organization_public_id=organization_public_id,
                    generation=replace(
                        generation,
                        status=GenerationStatus.FAILED,
                        completed_at=created_at + timedelta(milliseconds=1),
                        error_kind="test_history_setup",
                    ),
                )
            )

    assert prepared == tuple(messages[-3:])


def test_prepare_generation_rolls_back_message_when_generation_is_invalid(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    message, generation = _generation(conversation)
    invalid_generation = replace(generation, user_message_public_id=uuid4())

    with pytest.raises(ConversationReferenceError):
        asyncio.run(
            _persistence(conversation_async_session_factory).prepare_generation(
                organization_public_id=organization_public_id,
                conversation=conversation,
                message=message,
                generation=invalid_generation,
                history_limit=10,
            )
        )

    with Session(migrated_streaming_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == message.public_id
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(GenerationModel.id)).where(
                    GenerationModel.public_id == generation.public_id
                )
            )
            == 0
        )


def test_complete_generation_commits_assistant_and_completion_state(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    message, generation = _generation(conversation)
    asyncio.run(
        _persistence(conversation_async_session_factory).prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=10,
        )
    )
    assistant = Message(
        public_id=uuid4(),
        conversation_public_id=conversation.public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Completed response",
        created_at=TIMESTAMP + timedelta(seconds=1),
    )
    completed = replace(
        generation,
        assistant_message_public_id=assistant.public_id,
        status=GenerationStatus.COMPLETED,
        finish_reason=GenerationFinishReason.STOP,
        input_tokens=3,
        output_tokens=4,
        total_tokens=7,
        completed_at=TIMESTAMP + timedelta(seconds=1),
    )

    asyncio.run(
        _persistence(conversation_async_session_factory).complete_generation(
            organization_public_id=organization_public_id,
            assistant_message=assistant,
            generation=completed,
        )
    )

    with Session(migrated_streaming_engine) as session:
        stored_generation = session.scalar(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        )
        assert stored_generation is not None
        assert stored_generation.status == GenerationStatus.COMPLETED.value
        assert stored_generation.assistant_message_id is not None
        assert stored_generation.finish_reason == GenerationFinishReason.STOP.value
        assert stored_generation.total_tokens == 7
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == assistant.public_id
                )
            )
            == 1
        )


@pytest.mark.parametrize(
    ("operation", "status", "error_kind"),
    [
        ("fail_generation", GenerationStatus.FAILED, "provider_unavailable"),
        ("cancel_generation", GenerationStatus.CANCELLED, None),
    ],
)
def test_terminal_failure_operations_commit_generation_without_assistant(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    operation: str,
    status: GenerationStatus,
    error_kind: str | None,
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    message, generation = _generation(conversation)
    persistence = _persistence(conversation_async_session_factory)
    asyncio.run(
        persistence.prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=10,
        )
    )
    terminal = replace(
        generation,
        status=status,
        completed_at=TIMESTAMP + timedelta(seconds=1),
        error_kind=error_kind,
    )

    asyncio.run(
        getattr(persistence, operation)(
            organization_public_id=organization_public_id,
            generation=terminal,
        )
    )

    with Session(migrated_streaming_engine) as session:
        stored = session.scalar(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        )
        assert stored is not None
        assert stored.status == status.value
        assert stored.completed_at is not None
        assert stored.error_kind == error_kind
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.conversation_id == stored.conversation_id,
                    MessageModel.role == ConversationMessageRole.ASSISTANT.value,
                )
            )
            == 0
        )


def test_complete_generation_rolls_back_assistant_when_generation_update_fails(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    persistence = _persistence(conversation_async_session_factory)
    other_conversation = replace(
        conversation,
        public_id=uuid4(),
        title="Other conversation in the same tenant",
    )
    asyncio.run(persistence.create_conversation(other_conversation))
    message, generation = _generation(conversation)
    asyncio.run(
        persistence.prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=10,
        )
    )
    assistant = Message(
        public_id=uuid4(),
        conversation_public_id=other_conversation.public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Wrong scope",
        created_at=TIMESTAMP,
    )
    invalid_generation = replace(
        generation,
        assistant_message_public_id=assistant.public_id,
        status=GenerationStatus.COMPLETED,
        finish_reason=GenerationFinishReason.STOP,
        completed_at=TIMESTAMP + timedelta(seconds=1),
    )

    with pytest.raises(
        ConversationReferenceError,
        match="assistant Message reference was not found",
    ):
        asyncio.run(
            persistence.complete_generation(
                organization_public_id=organization_public_id,
                assistant_message=assistant,
                generation=invalid_generation,
            )
        )

    with Session(migrated_streaming_engine) as session:
        stored_generation = session.scalar(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        )
        assert stored_generation is not None
        assert stored_generation.status == GenerationStatus.RUNNING.value
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == assistant.public_id
                )
            )
            == 0
        )


def test_concurrent_terminal_transitions_allow_exactly_one_winner(
    migrated_streaming_engine: Engine,
    conversation_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_public_id, conversation = _seed_conversation(
        migrated_streaming_engine,
        conversation_async_session_factory,
    )
    persistence = _persistence(conversation_async_session_factory)
    message, generation = _generation(conversation)
    asyncio.run(
        persistence.prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=10,
        )
    )
    completed_at = TIMESTAMP + timedelta(seconds=1)
    assistant = Message(
        public_id=uuid4(),
        conversation_public_id=conversation.public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Only a completed winner may persist this message",
        created_at=completed_at,
    )
    completed = replace(
        generation,
        assistant_message_public_id=assistant.public_id,
        status=GenerationStatus.COMPLETED,
        finish_reason=GenerationFinishReason.STOP,
        completed_at=completed_at,
    )
    failed = replace(
        generation,
        status=GenerationStatus.FAILED,
        completed_at=completed_at,
        error_kind="provider_failure",
    )
    cancelled = replace(
        generation,
        status=GenerationStatus.CANCELLED,
        completed_at=completed_at,
    )
    barrier = asyncio.Barrier(3)
    original_lock = queries.lock_generation_for_terminal_transition

    async def race_to_lock(
        *args: object,
        **kwargs: object,
    ) -> GenerationModel | None:
        await barrier.wait()
        return await original_lock(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        queries,
        "lock_generation_for_terminal_transition",
        race_to_lock,
    )

    async def race() -> tuple[bool, bool, bool]:
        completed_result, failed_result, cancelled_result = await asyncio.gather(
            persistence.complete_generation(
                organization_public_id=organization_public_id,
                assistant_message=assistant,
                generation=completed,
            ),
            persistence.fail_generation(
                organization_public_id=organization_public_id,
                generation=failed,
            ),
            persistence.cancel_generation(
                organization_public_id=organization_public_id,
                generation=cancelled,
            ),
        )
        return completed_result, failed_result, cancelled_result

    results = asyncio.run(race())

    assert results.count(True) == 1
    winning_status = (
        GenerationStatus.COMPLETED,
        GenerationStatus.FAILED,
        GenerationStatus.CANCELLED,
    )[results.index(True)]
    with Session(migrated_streaming_engine) as session:
        stored = session.scalar(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        )
        assert stored is not None
        assert stored.status == winning_status.value
        assistant_count = session.scalar(
            select(func.count(MessageModel.id)).where(
                MessageModel.public_id == assistant.public_id
            )
        )
        if winning_status is GenerationStatus.COMPLETED:
            assert stored.assistant_message_id is not None
            assert assistant_count == 1
        else:
            assert stored.assistant_message_id is None
            assert assistant_count == 0
