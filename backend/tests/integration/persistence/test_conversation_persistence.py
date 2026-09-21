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
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.persistence import (
    ConversationEntityNotFoundError,
    ConversationReferenceError,
)
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


@pytest.fixture
def migrated_engine(
    migrated_database: tuple[Config, Engine],
) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def _persistence(engine: Engine) -> SqlAlchemyConversationPersistence:
    return SqlAlchemyConversationPersistence(lambda: Session(engine))


def _seed_identity(engine: Engine) -> tuple[UUID, UUID]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Conversation Organization",
            slug=f"conversation-{uuid4().hex[:12]}",
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


def _conversation(
    organization_public_id: UUID,
    user_public_id: UUID,
    *,
    workspace_public_id: UUID | None = None,
    project_public_id: UUID | None = None,
) -> Conversation:
    return Conversation(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=user_public_id,
        workspace_public_id=workspace_public_id,
        project_public_id=project_public_id,
        title="Conversation",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )


def _message(
    conversation_public_id: UUID,
    content: str,
    *,
    role: ConversationMessageRole = ConversationMessageRole.USER,
) -> Message:
    return Message(
        public_id=uuid4(),
        conversation_public_id=conversation_public_id,
        role=role,
        content=content,
        created_at=TIMESTAMP,
    )


def _generation(
    conversation_public_id: UUID,
    user_message_public_id: UUID,
) -> Generation:
    return Generation(
        public_id=uuid4(),
        conversation_public_id=conversation_public_id,
        user_message_public_id=user_message_public_id,
        model="gpt-test",
        status=GenerationStatus.RUNNING,
        started_at=TIMESTAMP,
    )


def _create_conversation(
    persistence: SqlAlchemyConversationPersistence,
    conversation: Conversation,
) -> None:
    asyncio.run(persistence.create_conversation(conversation))


def _prepare_generation(
    persistence: SqlAlchemyConversationPersistence,
    organization_public_id: UUID,
    conversation: Conversation,
    message: Message,
    generation: Generation,
    *,
    history_limit: int = 10,
) -> tuple[Message, ...]:
    return asyncio.run(
        persistence.prepare_generation(
            organization_public_id=organization_public_id,
            conversation=conversation,
            message=message,
            generation=generation,
            history_limit=history_limit,
        )
    )


def test_persistence_preserves_conversation_scopes_and_tenant_identity(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversations = (
        _conversation(organization_public_id, user_public_id),
        _conversation(
            organization_public_id,
            user_public_id,
            workspace_public_id=uuid4(),
        ),
        _conversation(
            organization_public_id,
            user_public_id,
            workspace_public_id=uuid4(),
            project_public_id=uuid4(),
        ),
    )

    for conversation in conversations:
        _create_conversation(persistence, conversation)

    stored = tuple(
        asyncio.run(
            persistence.get_conversation(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation.public_id,
            )
        )
        for conversation in conversations
    )
    wrong_tenant = asyncio.run(
        persistence.get_conversation(
            organization_public_id=uuid4(),
            conversation_public_id=conversations[0].public_id,
        )
    )

    assert stored == conversations
    assert all(not hasattr(value, "id") for value in stored)
    assert wrong_tenant is None


def test_persistence_rejects_creator_from_another_tenant(
    migrated_engine: Engine,
) -> None:
    organization_a, _user_a = _seed_identity(migrated_engine)
    _organization_b, user_b = _seed_identity(migrated_engine)
    conversation = _conversation(organization_a, user_b)

    with pytest.raises(ConversationReferenceError):
        _create_conversation(_persistence(migrated_engine), conversation)

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(ConversationModel.id)).where(
                    ConversationModel.public_id == conversation.public_id
                )
            )
            == 0
        )


@pytest.mark.parametrize("limit", [0, -1])
def test_prepare_generation_rejects_non_positive_history_limit_atomically(
    migrated_engine: Engine,
    limit: int,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    message = _message(conversation.public_id, "request")
    generation = _generation(conversation.public_id, message.public_id)

    with pytest.raises(ValueError, match="limit"):
        _prepare_generation(
            persistence,
            organization_public_id,
            conversation,
            message,
            generation,
            history_limit=limit,
        )

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(MessageModel.id))) == 0
        assert session.scalar(select(func.count(GenerationModel.id))) == 0


def test_prepare_generation_rejects_a_conversation_from_another_tenant(
    migrated_engine: Engine,
) -> None:
    organization_a, _user_a = _seed_identity(migrated_engine)
    organization_b, user_b = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_b, user_b)
    _create_conversation(persistence, conversation)
    message = _message(conversation.public_id, "other tenant")
    generation = _generation(conversation.public_id, message.public_id)

    with pytest.raises(ConversationReferenceError):
        _prepare_generation(
            persistence,
            organization_a,
            conversation,
            message,
            generation,
        )

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == message.public_id
                )
            )
            == 0
        )


def test_prepare_generation_rejects_a_cross_conversation_message_reference(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    first = _conversation(organization_public_id, user_public_id)
    second = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, first)
    _create_conversation(persistence, second)

    second_message = _message(second.public_id, "second conversation")
    _prepare_generation(
        persistence,
        organization_public_id,
        second,
        second_message,
        _generation(second.public_id, second_message.public_id),
    )
    first_message = _message(first.public_id, "first conversation")
    invalid_generation = _generation(first.public_id, second_message.public_id)

    with pytest.raises(ConversationReferenceError):
        _prepare_generation(
            persistence,
            organization_public_id,
            first,
            first_message,
            invalid_generation,
        )

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == first_message.public_id
                )
            )
            == 0
        )


def test_prepare_generation_rejects_a_cross_tenant_message_reference(
    migrated_engine: Engine,
) -> None:
    organization_a, user_a = _seed_identity(migrated_engine)
    organization_b, user_b = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    first = _conversation(organization_a, user_a)
    second = _conversation(organization_b, user_b)
    _create_conversation(persistence, first)
    _create_conversation(persistence, second)

    second_message = _message(second.public_id, "second tenant")
    _prepare_generation(
        persistence,
        organization_b,
        second,
        second_message,
        _generation(second.public_id, second_message.public_id),
    )
    first_message = _message(first.public_id, "first tenant")
    invalid_generation = _generation(first.public_id, second_message.public_id)

    with pytest.raises(ConversationReferenceError):
        _prepare_generation(
            persistence,
            organization_a,
            first,
            first_message,
            invalid_generation,
        )

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == first_message.public_id
                )
            )
            == 0
        )


def test_generation_update_rejects_another_tenant_without_leaking_state(
    migrated_engine: Engine,
) -> None:
    organization_a, user_a = _seed_identity(migrated_engine)
    organization_b, _user_b = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_a, user_a)
    _create_conversation(persistence, conversation)
    message = _message(conversation.public_id, "request")
    generation = _generation(conversation.public_id, message.public_id)
    _prepare_generation(
        persistence,
        organization_a,
        conversation,
        message,
        generation,
    )
    failed = replace(
        generation,
        status=GenerationStatus.FAILED,
        completed_at=TIMESTAMP + timedelta(seconds=1),
        error_kind="provider_timeout",
    )

    with pytest.raises(ConversationEntityNotFoundError):
        asyncio.run(
            persistence.fail_generation(
                organization_public_id=organization_b,
                generation=failed,
            )
        )

    with Session(migrated_engine) as session:
        stored = session.scalars(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        ).one()
        assert stored.status == GenerationStatus.RUNNING.value
        assert stored.completed_at is None
        assert stored.error_kind is None


def test_fail_generation_persists_terminal_lifecycle(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    message = _message(conversation.public_id, "request")
    generation = _generation(conversation.public_id, message.public_id)
    _prepare_generation(
        persistence,
        organization_public_id,
        conversation,
        message,
        generation,
    )
    failed = replace(
        generation,
        status=GenerationStatus.FAILED,
        completed_at=TIMESTAMP + timedelta(seconds=1),
        error_kind="provider_timeout",
    )

    asyncio.run(
        persistence.fail_generation(
            organization_public_id=organization_public_id,
            generation=failed,
        )
    )

    with Session(migrated_engine) as session:
        stored = session.scalars(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        ).one()
        assert stored.status == GenerationStatus.FAILED.value
        assert stored.error_kind == "provider_timeout"
        assert stored.started_at == TIMESTAMP
        assert stored.completed_at == TIMESTAMP + timedelta(seconds=1)
