from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.repositories import ConversationReferenceError
from nexus.infrastructure.persistence.conversation_operations import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.models.generation import (
    Generation as GenerationModel,
)
from nexus.infrastructure.persistence.models.message import Message as MessageModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.repositories.conversation import (
    SqlAlchemyConversationRepository,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_conversation(engine: Engine) -> tuple[UUID, Conversation]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    conversation = Conversation(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=user_public_id,
        title="Streaming conversation",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
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
        SqlAlchemyConversationRepository(session).add(conversation)
        session.commit()
    return organization_public_id, conversation


def _persistence(engine: Engine) -> SqlAlchemyConversationPersistence:
    return SqlAlchemyConversationPersistence(lambda: Session(engine))


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


def test_prepare_generation_commits_running_user_message_and_generation(
    migrated_streaming_engine: Engine,
) -> None:
    organization_public_id, conversation = _seed_conversation(migrated_streaming_engine)
    message, generation = _generation(conversation)

    prepared = asyncio.run(
        _persistence(migrated_streaming_engine).prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=10,
        )
    )

    assert prepared.conversation == conversation
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


def test_complete_generation_commits_assistant_and_completion_state(
    migrated_streaming_engine: Engine,
) -> None:
    organization_public_id, conversation = _seed_conversation(migrated_streaming_engine)
    message, generation = _generation(conversation)
    asyncio.run(
        _persistence(migrated_streaming_engine).prepare_generation(
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
        _persistence(migrated_streaming_engine).complete_generation(
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
    operation: str,
    status: GenerationStatus,
    error_kind: str | None,
) -> None:
    organization_public_id, conversation = _seed_conversation(migrated_streaming_engine)
    message, generation = _generation(conversation)
    persistence = _persistence(migrated_streaming_engine)
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
) -> None:
    organization_public_id, conversation = _seed_conversation(migrated_streaming_engine)
    _organization_public_id, other_conversation = _seed_conversation(
        migrated_streaming_engine
    )
    message, generation = _generation(conversation)
    persistence = _persistence(migrated_streaming_engine)
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

    with pytest.raises(ConversationReferenceError):
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
