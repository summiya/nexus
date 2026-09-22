from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from nexus.conversations.application.list_conversations import ListConversations
from nexus.conversations.domain import Conversation
from nexus.conversations.ports.persistence import ConversationPersistenceError
from nexus.errors import ErrorCode, NexusError

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


class StubPersistence:
    def __init__(self, conversations: tuple[Conversation, ...] = ()) -> None:
        self.conversations = conversations
        self.calls: list[tuple[UUID, UUID]] = []
        self.error: Exception | None = None

    async def list_conversations(
        self,
        *,
        organization_public_id: UUID,
        created_by_user_public_id: UUID,
    ) -> tuple[Conversation, ...]:
        self.calls.append((organization_public_id, created_by_user_public_id))
        if self.error is not None:
            raise self.error
        return self.conversations


def _conversation(created_at: datetime) -> Conversation:
    return Conversation(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        title="Conversation",
        created_at=created_at,
        updated_at=created_at,
    )


def test_execute_delegates_the_exact_organization_and_user_scope() -> None:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    persistence = StubPersistence()

    asyncio.run(
        ListConversations(persistence=persistence).execute(  # type: ignore[arg-type]
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
        )
    )

    assert persistence.calls == [(organization_public_id, user_public_id)]


def test_execute_preserves_persistence_ordering() -> None:
    newest = _conversation(TIMESTAMP + timedelta(minutes=1))
    oldest = _conversation(TIMESTAMP)
    persistence = StubPersistence((newest, oldest))

    result = asyncio.run(
        ListConversations(persistence=persistence).execute(  # type: ignore[arg-type]
            organization_public_id=uuid4(),
            user_public_id=uuid4(),
        )
    )

    assert result == (newest, oldest)


def test_execute_translates_conversation_persistence_failure() -> None:
    persistence = StubPersistence()
    persistence.error = ConversationPersistenceError("database unavailable")

    with pytest.raises(NexusError) as exc_info:
        asyncio.run(
            ListConversations(persistence=persistence).execute(  # type: ignore[arg-type]
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
            )
        )

    error = exc_info.value
    assert error.code is ErrorCode.SERVICE_UNAVAILABLE
    assert error.message == "The conversations could not be retrieved."
    assert error.retryable is True
    assert isinstance(error.__cause__, ConversationPersistenceError)
