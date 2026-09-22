from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from nexus.conversations.domain import (
    Conversation,
    ConversationGenerationMetadata,
    ConversationMessageHistoryItem,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.persistence import (
    ConversationEntityNotFoundError,
    ConversationPersistenceError,
    ConversationReferenceError,
)
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


def _seed_user(engine: Engine, organization_public_id: UUID) -> UUID:
    user_public_id = uuid4()
    with Session(engine) as session:
        organization_id = session.scalar(
            select(Organization.id).where(
                Organization.public_id == organization_public_id
            )
        )
        assert organization_id is not None
        session.add(
            User(
                public_id=user_public_id,
                organization_id=organization_id,
                email=f"{uuid4().hex}@example.com",
                status="active",
            )
        )
        session.commit()
    return user_public_id


def _conversation(
    organization_public_id: UUID,
    user_public_id: UUID,
    *,
    created_at: datetime = TIMESTAMP,
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
        created_at=created_at,
        updated_at=created_at,
    )


def _message(
    conversation_public_id: UUID,
    content: str,
    *,
    role: ConversationMessageRole = ConversationMessageRole.USER,
    created_at: datetime = TIMESTAMP,
) -> Message:
    return Message(
        public_id=uuid4(),
        conversation_public_id=conversation_public_id,
        role=role,
        content=content,
        created_at=created_at,
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


def _list_conversations(
    persistence: SqlAlchemyConversationPersistence,
    organization_public_id: UUID,
    user_public_id: UUID,
) -> tuple[Conversation, ...]:
    return asyncio.run(
        persistence.list_conversations(
            organization_public_id=organization_public_id,
            created_by_user_public_id=user_public_id,
        )
    )


def _list_messages(
    persistence: SqlAlchemyConversationPersistence,
    organization_public_id: UUID,
    conversation_public_id: UUID,
) -> tuple[ConversationMessageHistoryItem, ...]:
    return asyncio.run(
        persistence.list_messages(
            organization_public_id=organization_public_id,
            conversation_public_id=conversation_public_id,
        )
    )


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


def _persist_turn(
    persistence: SqlAlchemyConversationPersistence,
    organization_public_id: UUID,
    conversation: Conversation,
    *,
    user_content: str,
    assistant_content: str,
    user_created_at: datetime = TIMESTAMP,
    assistant_created_at: datetime = TIMESTAMP,
    model: str = "gpt-test",
    finish_reason: GenerationFinishReason = GenerationFinishReason.STOP,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
) -> tuple[Message, Message, Generation]:
    user_message = _message(
        conversation.public_id,
        user_content,
        created_at=user_created_at,
    )
    generation = replace(
        _generation(conversation.public_id, user_message.public_id),
        model=model,
        started_at=user_created_at,
    )
    _prepare_generation(
        persistence,
        organization_public_id,
        conversation,
        user_message,
        generation,
    )
    assistant_message = _message(
        conversation.public_id,
        assistant_content,
        role=ConversationMessageRole.ASSISTANT,
        created_at=assistant_created_at,
    )
    completed = replace(
        generation,
        assistant_message_public_id=assistant_message.public_id,
        status=GenerationStatus.COMPLETED,
        finish_reason=finish_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        completed_at=assistant_created_at,
    )
    transitioned = asyncio.run(
        persistence.complete_generation(
            organization_public_id=organization_public_id,
            assistant_message=assistant_message,
            generation=completed,
        )
    )
    assert transitioned is True
    return user_message, assistant_message, completed


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


def test_list_conversations_returns_the_requested_users_conversations(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)

    listed = _list_conversations(
        persistence,
        organization_public_id,
        user_public_id,
    )

    assert listed == (conversation,)
    assert not hasattr(listed[0], "id")


def test_list_conversations_excludes_another_user_in_the_same_organization(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    other_user_public_id = _seed_user(migrated_engine, organization_public_id)
    persistence = _persistence(migrated_engine)
    requested_user_conversation = _conversation(
        organization_public_id,
        user_public_id,
    )
    other_user_conversation = _conversation(
        organization_public_id,
        other_user_public_id,
    )
    _create_conversation(persistence, requested_user_conversation)
    _create_conversation(persistence, other_user_conversation)

    listed = _list_conversations(
        persistence,
        organization_public_id,
        user_public_id,
    )

    assert listed == (requested_user_conversation,)


def test_list_conversations_excludes_another_organization(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    other_organization_public_id, other_user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    requested_organization_conversation = _conversation(
        organization_public_id,
        user_public_id,
    )
    other_organization_conversation = _conversation(
        other_organization_public_id,
        other_user_public_id,
    )
    _create_conversation(persistence, requested_organization_conversation)
    _create_conversation(persistence, other_organization_conversation)

    listed = _list_conversations(
        persistence,
        organization_public_id,
        user_public_id,
    )

    assert listed == (requested_organization_conversation,)
    assert (
        _list_conversations(
            persistence,
            organization_public_id,
            other_user_public_id,
        )
        == ()
    )


def test_list_conversations_orders_newest_first(migrated_engine: Engine) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    oldest = _conversation(
        organization_public_id,
        user_public_id,
        created_at=TIMESTAMP,
    )
    newest = _conversation(
        organization_public_id,
        user_public_id,
        created_at=TIMESTAMP + timedelta(minutes=2),
    )
    middle = _conversation(
        organization_public_id,
        user_public_id,
        created_at=TIMESTAMP + timedelta(minutes=1),
    )
    for conversation in (oldest, newest, middle):
        _create_conversation(persistence, conversation)

    listed = _list_conversations(
        persistence,
        organization_public_id,
        user_public_id,
    )

    assert listed == (newest, middle, oldest)


def test_list_conversations_orders_equal_timestamps_deterministically(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    first = _conversation(organization_public_id, user_public_id)
    second = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, first)
    _create_conversation(persistence, second)

    listed = _list_conversations(
        persistence,
        organization_public_id,
        user_public_id,
    )

    assert listed == (second, first)


def test_list_conversations_returns_empty_tuple(migrated_engine: Engine) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)

    listed = _list_conversations(
        _persistence(migrated_engine),
        organization_public_id,
        user_public_id,
    )

    assert listed == ()


def test_list_messages_returns_completed_assistant_generation_metadata(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    user_message, assistant_message, generation = _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="Question",
        assistant_content="Answer",
        user_created_at=TIMESTAMP,
        assistant_created_at=TIMESTAMP + timedelta(seconds=1),
        model="gpt-metadata",
        finish_reason=GenerationFinishReason.LENGTH,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
    )

    listed = _list_messages(
        persistence,
        organization_public_id,
        conversation.public_id,
    )

    assert tuple(item.message for item in listed) == (
        user_message,
        assistant_message,
    )
    assert listed[0].generation is None
    assert listed[1].generation == ConversationGenerationMetadata(
        public_id=generation.public_id,
        model="gpt-metadata",
        status=GenerationStatus.COMPLETED,
        finish_reason=GenerationFinishReason.LENGTH,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP + timedelta(seconds=1),
        error_kind=None,
    )


def test_list_messages_returns_none_for_unassociated_system_and_assistant_messages(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    system_message = _message(
        conversation.public_id,
        "System instruction",
        role=ConversationMessageRole.SYSTEM,
    )
    assistant_message = _message(
        conversation.public_id,
        "Historical answer",
        role=ConversationMessageRole.ASSISTANT,
        created_at=TIMESTAMP + timedelta(seconds=1),
    )
    with Session(migrated_engine) as session:
        queries.insert_message(
            session,
            organization_public_id=organization_public_id,
            message=system_message,
        )
        queries.insert_message(
            session,
            organization_public_id=organization_public_id,
            message=assistant_message,
        )
        session.commit()

    listed = _list_messages(
        persistence,
        organization_public_id,
        conversation.public_id,
    )

    assert tuple(item.message for item in listed) == (
        system_message,
        assistant_message,
    )
    assert all(item.generation is None for item in listed)


def test_list_messages_orders_oldest_to_newest(migrated_engine: Engine) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    first_user, first_assistant, _first_generation = _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="First question",
        assistant_content="First answer",
        user_created_at=TIMESTAMP,
        assistant_created_at=TIMESTAMP + timedelta(seconds=1),
    )
    second_user, second_assistant, _second_generation = _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="Second question",
        assistant_content="Second answer",
        user_created_at=TIMESTAMP + timedelta(seconds=2),
        assistant_created_at=TIMESTAMP + timedelta(seconds=3),
    )

    listed = _list_messages(
        persistence,
        organization_public_id,
        conversation.public_id,
    )

    assert tuple(item.message for item in listed) == (
        first_user,
        first_assistant,
        second_user,
        second_assistant,
    )


def test_list_messages_orders_equal_timestamps_by_internal_id(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    first_turn = _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="First question",
        assistant_content="First answer",
    )
    second_turn = _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="Second question",
        assistant_content="Second answer",
    )

    listed = _list_messages(
        persistence,
        organization_public_id,
        conversation.public_id,
    )

    assert tuple(item.message for item in listed) == (
        first_turn[0],
        first_turn[1],
        second_turn[0],
        second_turn[1],
    )


def test_list_messages_returns_empty_tuple_for_existing_empty_conversation(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)

    listed = _list_messages(
        persistence,
        organization_public_id,
        conversation.public_id,
    )

    assert listed == ()


def test_list_messages_excludes_messages_from_another_conversation(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    requested = _conversation(organization_public_id, user_public_id)
    other = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, requested)
    _create_conversation(persistence, other)
    requested_turn = _persist_turn(
        persistence,
        organization_public_id,
        requested,
        user_content="Requested question",
        assistant_content="Requested answer",
    )
    other_turn = _persist_turn(
        persistence,
        organization_public_id,
        other,
        user_content="Other question",
        assistant_content="Other answer",
    )

    listed = _list_messages(
        persistence,
        organization_public_id,
        requested.public_id,
    )

    assert tuple(item.message for item in listed) == requested_turn[:2]
    assert listed[1].generation is not None
    assert listed[1].generation.public_id == requested_turn[2].public_id
    assert listed[1].generation.public_id != other_turn[2].public_id


def test_list_messages_does_not_expose_another_organization(
    migrated_engine: Engine,
) -> None:
    organization_a, _user_a = _seed_identity(migrated_engine)
    organization_b, user_b = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_b, user_b)
    _create_conversation(persistence, conversation)
    _persist_turn(
        persistence,
        organization_b,
        conversation,
        user_content="Private question",
        assistant_content="Private answer",
    )

    listed = _list_messages(
        persistence,
        organization_a,
        conversation.public_id,
    )

    assert listed == ()


def test_list_messages_returns_empty_tuple_for_unknown_conversation(
    migrated_engine: Engine,
) -> None:
    organization_public_id, _user_public_id = _seed_identity(migrated_engine)

    listed = _list_messages(
        _persistence(migrated_engine),
        organization_public_id,
        uuid4(),
    )

    assert listed == ()


def test_list_messages_returns_domain_records_without_internal_ids(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="Question",
        assistant_content="Answer",
    )

    listed = _list_messages(
        persistence,
        organization_public_id,
        conversation.public_id,
    )

    assert all(isinstance(item, ConversationMessageHistoryItem) for item in listed)
    assert all(isinstance(item.message, Message) for item in listed)
    assert all(not hasattr(item.message, "id") for item in listed)
    assert all(not hasattr(item.message, "organization_id") for item in listed)
    assert all(not hasattr(item.message, "conversation_id") for item in listed)
    assert all(
        item.generation is None or not hasattr(item.generation, "id") for item in listed
    )


def test_list_messages_uses_fixed_query_count_for_multiple_turns(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="First question",
        assistant_content="First answer",
    )
    _persist_turn(
        persistence,
        organization_public_id,
        conversation,
        user_content="Second question",
        assistant_content="Second answer",
    )
    query_count = 0

    def count_query(*_args: object) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(migrated_engine, "before_cursor_execute", count_query)
    try:
        listed = _list_messages(
            persistence,
            organization_public_id,
            conversation.public_id,
        )
    finally:
        event.remove(migrated_engine, "before_cursor_execute", count_query)

    assert len(listed) == 4
    assert query_count == 2


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


def test_unexpected_integrity_failure_is_not_translated_to_a_conflict(
    migrated_engine: Engine,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    persistence = _persistence(migrated_engine)
    conversation = _conversation(organization_public_id, user_public_id)
    _create_conversation(persistence, conversation)
    first_message = _message(conversation.public_id, "first")
    first_generation = _generation(conversation.public_id, first_message.public_id)
    _prepare_generation(
        persistence,
        organization_public_id,
        conversation,
        first_message,
        first_generation,
    )
    asyncio.run(
        persistence.fail_generation(
            organization_public_id=organization_public_id,
            generation=replace(
                first_generation,
                status=GenerationStatus.FAILED,
                completed_at=TIMESTAMP + timedelta(seconds=1),
                error_kind="test_setup",
            ),
        )
    )
    second_message = _message(conversation.public_id, "second")
    duplicate_public_id = replace(
        _generation(conversation.public_id, second_message.public_id),
        public_id=first_generation.public_id,
    )

    with pytest.raises(ConversationPersistenceError):
        _prepare_generation(
            persistence,
            organization_public_id,
            conversation,
            second_message,
            duplicate_public_id,
        )

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(func.count(MessageModel.id)).where(
                    MessageModel.public_id == second_message.public_id
                )
            )
            == 0
        )
        assert session.scalar(select(func.count(GenerationModel.id))) == 1


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
