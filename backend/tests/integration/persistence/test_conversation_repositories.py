from __future__ import annotations

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
from nexus.conversations.ports.repositories import (
    ConversationEntityNotFoundError,
    ConversationReferenceError,
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
from nexus.infrastructure.persistence.repositories.conversation import (
    SqlAlchemyConversationRepository,
)
from nexus.infrastructure.persistence.repositories.generation import (
    SqlAlchemyGenerationRepository,
)
from nexus.infrastructure.persistence.repositories.message import (
    SqlAlchemyMessageRepository,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def migrated_engine(
    migrated_database: tuple[Config, Engine],
) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def seed_identity(engine: Engine) -> tuple[UUID, UUID]:
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


def make_conversation(
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


def make_message(
    conversation_public_id: UUID,
    content: str,
    *,
    created_at: datetime = TIMESTAMP,
    role: ConversationMessageRole = ConversationMessageRole.USER,
) -> Message:
    return Message(
        public_id=uuid4(),
        conversation_public_id=conversation_public_id,
        role=role,
        content=content,
        created_at=created_at,
    )


def make_generation(
    conversation_public_id: UUID,
    user_message_public_id: UUID,
    *,
    assistant_message_public_id: UUID | None = None,
    status: GenerationStatus = GenerationStatus.PENDING,
    finish_reason: GenerationFinishReason | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error_kind: str | None = None,
) -> Generation:
    return Generation(
        public_id=uuid4(),
        conversation_public_id=conversation_public_id,
        user_message_public_id=user_message_public_id,
        assistant_message_public_id=assistant_message_public_id,
        model="gpt-test",
        status=status,
        finish_reason=finish_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        started_at=started_at,
        completed_at=completed_at,
        error_kind=error_kind,
    )


def test_conversation_repository_preserves_scopes_and_tenant_identity(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversations = [
        make_conversation(organization_public_id, user_public_id),
        make_conversation(
            organization_public_id,
            user_public_id,
            workspace_public_id=uuid4(),
        ),
        make_conversation(
            organization_public_id,
            user_public_id,
            workspace_public_id=uuid4(),
            project_public_id=uuid4(),
        ),
    ]

    with Session(migrated_engine) as session:
        repository = SqlAlchemyConversationRepository(session)
        for conversation in conversations:
            repository.add(conversation)
        session.commit()

    with Session(migrated_engine) as session:
        repository = SqlAlchemyConversationRepository(session)
        values = [
            repository.get(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation.public_id,
            )
            for conversation in conversations
        ]
        wrong_tenant = repository.get(
            organization_public_id=uuid4(),
            conversation_public_id=conversations[0].public_id,
        )

    assert values == conversations
    assert all(not hasattr(value, "id") for value in values)
    assert wrong_tenant is None


def test_conversation_repository_rejects_creator_from_another_tenant(
    migrated_engine: Engine,
) -> None:
    organization_a, _ = seed_identity(migrated_engine)
    _organization_b, user_b = seed_identity(migrated_engine)
    conversation = make_conversation(organization_a, user_b)

    with Session(migrated_engine) as session, pytest.raises(ConversationReferenceError):
        SqlAlchemyConversationRepository(session).add(conversation)
        session.rollback()

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(ConversationModel.id)).where(
                    ConversationModel.public_id == conversation.public_id
                )
            )
            == 0
        )


def test_message_repository_returns_most_recent_messages_in_chronological_order(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversation = make_conversation(organization_public_id, user_public_id)
    messages = [
        make_message(conversation.public_id, f"message-{index}") for index in range(5)
    ]

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        repository = SqlAlchemyMessageRepository(session)
        for message in messages:
            repository.add(
                organization_public_id=organization_public_id,
                message=message,
            )
        session.commit()

    with Session(migrated_engine) as session:
        repository = SqlAlchemyMessageRepository(session)
        recent = repository.list_recent_for_conversation(
            organization_public_id=organization_public_id,
            conversation_public_id=conversation.public_id,
            limit=3,
        )

    assert [message.content for message in recent] == [
        "message-2",
        "message-3",
        "message-4",
    ]
    assert all(isinstance(message, Message) for message in recent)


@pytest.mark.parametrize("limit", [0, -1])
def test_message_history_rejects_non_positive_limits(
    migrated_engine: Engine,
    limit: int,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversation = make_conversation(organization_public_id, user_public_id)

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        session.commit()
        repository = SqlAlchemyMessageRepository(session)
        with pytest.raises(ValueError, match="limit"):
            repository.list_recent_for_conversation(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation.public_id,
                limit=limit,
            )


def test_message_history_is_tenant_scoped_and_session_independent(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversation = make_conversation(organization_public_id, user_public_id)
    message = make_message(conversation.public_id, "session-independent")

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        SqlAlchemyMessageRepository(session).add(
            organization_public_id=organization_public_id,
            message=message,
        )
        session.commit()

    with Session(migrated_engine) as session:
        repository = SqlAlchemyMessageRepository(session)
        assert (
            repository.list_recent_for_conversation(
                organization_public_id=uuid4(),
                conversation_public_id=conversation.public_id,
                limit=10,
            )
            == []
        )
        returned = repository.list_recent_for_conversation(
            organization_public_id=organization_public_id,
            conversation_public_id=conversation.public_id,
            limit=10,
        )

    assert returned == [message]


def test_message_repository_rejects_conversation_from_another_tenant(
    migrated_engine: Engine,
) -> None:
    organization_a, _ = seed_identity(migrated_engine)
    organization_b, user_b = seed_identity(migrated_engine)
    conversation = make_conversation(organization_b, user_b)
    message = make_message(conversation.public_id, "other tenant")

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        session.commit()

    with Session(migrated_engine) as session, pytest.raises(ConversationReferenceError):
        SqlAlchemyMessageRepository(session).add(
            organization_public_id=organization_a,
            message=message,
        )
        session.rollback()

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == message.public_id
                )
            )
            == 0
        )


def test_generation_repository_persists_lifecycle_and_usage(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversation = make_conversation(organization_public_id, user_public_id)
    user_message = make_message(conversation.public_id, "generate")
    assistant_message = make_message(
        conversation.public_id,
        "response",
        role=ConversationMessageRole.ASSISTANT,
    )

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        message_repository = SqlAlchemyMessageRepository(session)
        for message in (user_message, assistant_message):
            message_repository.add(
                organization_public_id=organization_public_id,
                message=message,
            )
        generation_repository = SqlAlchemyGenerationRepository(session)
        pending = make_generation(conversation.public_id, user_message.public_id)
        generation_repository.add(
            organization_public_id=organization_public_id,
            generation=pending,
        )
        session.commit()

    completed = Generation(
        public_id=pending.public_id,
        conversation_public_id=conversation.public_id,
        user_message_public_id=user_message.public_id,
        assistant_message_public_id=assistant_message.public_id,
        model="gpt-test",
        status=GenerationStatus.COMPLETED,
        finish_reason=GenerationFinishReason.STOP,
        input_tokens=4,
        output_tokens=3,
        total_tokens=7,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP + timedelta(seconds=1),
    )
    with Session(migrated_engine) as session:
        SqlAlchemyGenerationRepository(session).update(
            organization_public_id=organization_public_id,
            generation=completed,
        )
        session.commit()

    with Session(migrated_engine) as session:
        stored = session.scalars(
            select(GenerationModel).where(
                GenerationModel.public_id == pending.public_id
            )
        ).one()

    assert stored.status == GenerationStatus.COMPLETED.value
    assert stored.finish_reason == GenerationFinishReason.STOP.value
    assert stored.input_tokens == 4
    assert stored.output_tokens == 3
    assert stored.total_tokens == 7
    assert stored.assistant_message_id is not None


def test_generation_rejects_cross_conversation_message_reference(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    first = make_conversation(organization_public_id, user_public_id)
    second = make_conversation(organization_public_id, user_public_id)
    message = make_message(second.public_id, "other conversation")

    with Session(migrated_engine) as session:
        conversation_repository = SqlAlchemyConversationRepository(session)
        conversation_repository.add(first)
        conversation_repository.add(second)
        SqlAlchemyMessageRepository(session).add(
            organization_public_id=organization_public_id,
            message=message,
        )
        session.commit()

    with Session(migrated_engine) as session, pytest.raises(ConversationReferenceError):
        SqlAlchemyGenerationRepository(session).add(
            organization_public_id=organization_public_id,
            generation=make_generation(first.public_id, message.public_id),
        )


def test_generation_rejects_cross_tenant_message_reference(
    migrated_engine: Engine,
) -> None:
    first_organization_id, first_user_id = seed_identity(migrated_engine)
    second_organization_id, second_user_id = seed_identity(migrated_engine)
    first = make_conversation(first_organization_id, first_user_id)
    second = make_conversation(second_organization_id, second_user_id)
    message = make_message(second.public_id, "other tenant")

    with Session(migrated_engine) as session:
        conversation_repository = SqlAlchemyConversationRepository(session)
        conversation_repository.add(first)
        conversation_repository.add(second)
        SqlAlchemyMessageRepository(session).add(
            organization_public_id=second_organization_id,
            message=message,
        )
        session.commit()

    with Session(migrated_engine) as session, pytest.raises(ConversationReferenceError):
        SqlAlchemyGenerationRepository(session).add(
            organization_public_id=first_organization_id,
            generation=make_generation(first.public_id, message.public_id),
        )


def test_generation_update_rejects_another_tenant_without_leaking_state(
    migrated_engine: Engine,
) -> None:
    organization_a, user_a = seed_identity(migrated_engine)
    organization_b, _ = seed_identity(migrated_engine)
    conversation = make_conversation(organization_a, user_a)
    user_message = make_message(conversation.public_id, "request")
    generation = make_generation(conversation.public_id, user_message.public_id)

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        SqlAlchemyMessageRepository(session).add(
            organization_public_id=organization_a,
            message=user_message,
        )
        SqlAlchemyGenerationRepository(session).add(
            organization_public_id=organization_a,
            generation=generation,
        )
        session.commit()

    attempted_update = replace(
        generation,
        status=GenerationStatus.RUNNING,
        started_at=TIMESTAMP,
    )
    with (
        Session(migrated_engine) as session,
        pytest.raises(ConversationEntityNotFoundError),
    ):
        SqlAlchemyGenerationRepository(session).update(
            organization_public_id=organization_b,
            generation=attempted_update,
        )
        session.rollback()

    with Session(migrated_engine) as session:
        stored = session.scalars(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        ).one()
    assert stored.status == GenerationStatus.PENDING.value
    assert stored.started_at is None


def test_generation_repository_persists_failed_lifecycle(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversation = make_conversation(organization_public_id, user_public_id)
    user_message = make_message(conversation.public_id, "request")
    generation = make_generation(conversation.public_id, user_message.public_id)

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        SqlAlchemyMessageRepository(session).add(
            organization_public_id=organization_public_id,
            message=user_message,
        )
        SqlAlchemyGenerationRepository(session).add(
            organization_public_id=organization_public_id,
            generation=generation,
        )
        session.commit()

    failed = replace(
        generation,
        status=GenerationStatus.FAILED,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP + timedelta(seconds=1),
        error_kind="provider_timeout",
    )
    with Session(migrated_engine) as session:
        SqlAlchemyGenerationRepository(session).update(
            organization_public_id=organization_public_id,
            generation=failed,
        )
        session.commit()

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


def test_generation_update_rejects_assistant_message_from_another_conversation(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    first = make_conversation(organization_public_id, user_public_id)
    second = make_conversation(organization_public_id, user_public_id)
    user_message = make_message(first.public_id, "request")
    assistant_message = make_message(
        second.public_id,
        "response",
        role=ConversationMessageRole.ASSISTANT,
    )
    generation = make_generation(first.public_id, user_message.public_id)

    with Session(migrated_engine) as session:
        conversation_repository = SqlAlchemyConversationRepository(session)
        conversation_repository.add(first)
        conversation_repository.add(second)
        message_repository = SqlAlchemyMessageRepository(session)
        message_repository.add(
            organization_public_id=organization_public_id,
            message=user_message,
        )
        message_repository.add(
            organization_public_id=organization_public_id,
            message=assistant_message,
        )
        SqlAlchemyGenerationRepository(session).add(
            organization_public_id=organization_public_id,
            generation=generation,
        )
        session.commit()

    attempted_update = replace(
        generation,
        assistant_message_public_id=assistant_message.public_id,
        status=GenerationStatus.COMPLETED,
        completed_at=TIMESTAMP,
    )
    with Session(migrated_engine) as session, pytest.raises(ConversationReferenceError):
        SqlAlchemyGenerationRepository(session).update(
            organization_public_id=organization_public_id,
            generation=attempted_update,
        )
        session.rollback()

    with Session(migrated_engine) as session:
        stored = session.scalars(
            select(GenerationModel).where(
                GenerationModel.public_id == generation.public_id
            )
        ).one()
    assert stored.assistant_message_id is None


def test_repository_add_does_not_commit_and_outer_rollback_removes_rows(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = seed_identity(migrated_engine)
    conversation = make_conversation(organization_public_id, user_public_id)

    with Session(migrated_engine) as session:
        SqlAlchemyConversationRepository(session).add(conversation)
        session.rollback()

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(ConversationModel.id))) == 0
