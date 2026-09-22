from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from nexus.conversations.application.get_conversation_messages import (
    GetConversationMessages,
)
from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Message,
)
from nexus.conversations.ports.persistence import ConversationPersistenceError
from nexus.errors import ErrorCode, NexusError

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
CONVERSATION_ID = uuid4()
TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


class StubPersistence:
    def __init__(
        self,
        conversation: Conversation | None,
        messages: tuple[Message, ...] = (),
    ) -> None:
        self.conversation = conversation
        self.messages = messages
        self.calls: list[tuple[str, UUID, UUID]] = []
        self.get_error: Exception | None = None
        self.list_error: Exception | None = None

    async def get_conversation(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        self.calls.append(
            ("get_conversation", organization_public_id, conversation_public_id)
        )
        if self.get_error is not None:
            raise self.get_error
        if organization_public_id != ORGANIZATION_ID:
            return None
        return self.conversation

    async def list_messages(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[Message, ...]:
        self.calls.append(
            ("list_messages", organization_public_id, conversation_public_id)
        )
        if self.list_error is not None:
            raise self.list_error
        return self.messages


def _conversation(
    *,
    created_by_user_public_id: UUID = USER_ID,
    workspace_public_id: UUID | None = None,
    project_public_id: UUID | None = None,
) -> Conversation:
    return Conversation(
        public_id=CONVERSATION_ID,
        organization_public_id=ORGANIZATION_ID,
        created_by_user_public_id=created_by_user_public_id,
        workspace_public_id=workspace_public_id,
        project_public_id=project_public_id,
        title="Conversation",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )


def _message(*, content: str, created_at: datetime = TIMESTAMP) -> Message:
    return Message(
        public_id=uuid4(),
        conversation_public_id=CONVERSATION_ID,
        role=ConversationMessageRole.USER,
        content=content,
        created_at=created_at,
    )


def _execute(
    persistence: StubPersistence,
    *,
    organization_public_id: UUID = ORGANIZATION_ID,
    user_public_id: UUID = USER_ID,
) -> tuple[Message, ...]:
    return asyncio.run(
        GetConversationMessages(  # type: ignore[arg-type]
            persistence=persistence
        ).execute(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            conversation_public_id=CONVERSATION_ID,
        )
    )


def test_execute_returns_messages_for_owned_standalone_conversation() -> None:
    message = _message(content="Hello")
    persistence = StubPersistence(_conversation(), (message,))

    result = _execute(persistence)

    assert result == (message,)


def test_execute_preserves_persistence_ordering() -> None:
    oldest = _message(content="First", created_at=TIMESTAMP)
    newest = _message(
        content="Second",
        created_at=TIMESTAMP + timedelta(minutes=1),
    )
    persistence = StubPersistence(_conversation(), (oldest, newest))

    result = _execute(persistence)

    assert result == (oldest, newest)


def test_execute_returns_safe_not_found_for_unknown_conversation() -> None:
    persistence = StubPersistence(None)

    with pytest.raises(NexusError) as exc_info:
        _execute(persistence)

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert exc_info.value.message == "The requested resource was not found."
    assert persistence.calls == [("get_conversation", ORGANIZATION_ID, CONVERSATION_ID)]


def test_execute_returns_safe_not_found_for_wrong_organization() -> None:
    persistence = StubPersistence(_conversation())

    with pytest.raises(NexusError) as exc_info:
        _execute(persistence, organization_public_id=uuid4())

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert exc_info.value.message == "The requested resource was not found."
    assert all(call[0] != "list_messages" for call in persistence.calls)


def test_execute_hides_standalone_conversation_from_another_user() -> None:
    persistence = StubPersistence(_conversation(created_by_user_public_id=uuid4()))

    with pytest.raises(NexusError) as exc_info:
        _execute(persistence)

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert exc_info.value.message == "The requested resource was not found."
    assert all(call[0] != "list_messages" for call in persistence.calls)


@pytest.mark.parametrize("project_scoped", [False, True])
def test_execute_forbids_workspace_and_project_conversations(
    project_scoped: bool,
) -> None:
    workspace_public_id = uuid4()
    persistence = StubPersistence(
        _conversation(
            workspace_public_id=workspace_public_id,
            project_public_id=uuid4() if project_scoped else None,
        )
    )

    with pytest.raises(NexusError) as exc_info:
        _execute(persistence)

    assert exc_info.value.code is ErrorCode.FORBIDDEN
    assert exc_info.value.message == "You are not allowed to perform this action."
    assert all(call[0] != "list_messages" for call in persistence.calls)


def test_execute_never_lists_messages_after_authorization_failure() -> None:
    persistence = StubPersistence(
        _conversation(created_by_user_public_id=uuid4()),
        (_message(content="Private"),),
    )

    with pytest.raises(NexusError):
        _execute(persistence)

    assert persistence.calls == [("get_conversation", ORGANIZATION_ID, CONVERSATION_ID)]


def test_execute_looks_up_then_lists_with_exact_tenant_scope() -> None:
    persistence = StubPersistence(_conversation())

    _execute(persistence)

    assert persistence.calls == [
        ("get_conversation", ORGANIZATION_ID, CONVERSATION_ID),
        ("list_messages", ORGANIZATION_ID, CONVERSATION_ID),
    ]


def test_execute_translates_conversation_lookup_failure() -> None:
    persistence = StubPersistence(_conversation())
    persistence.get_error = ConversationPersistenceError("database unavailable")

    with pytest.raises(NexusError) as exc_info:
        _execute(persistence)

    error = exc_info.value
    assert error.code is ErrorCode.SERVICE_UNAVAILABLE
    assert error.message == "The conversation messages could not be retrieved."
    assert error.retryable is True
    assert isinstance(error.__cause__, ConversationPersistenceError)
    assert all(call[0] != "list_messages" for call in persistence.calls)


def test_execute_translates_message_listing_failure() -> None:
    persistence = StubPersistence(_conversation())
    persistence.list_error = ConversationPersistenceError("database unavailable")

    with pytest.raises(NexusError) as exc_info:
        _execute(persistence)

    error = exc_info.value
    assert error.code is ErrorCode.SERVICE_UNAVAILABLE
    assert error.message == "The conversation messages could not be retrieved."
    assert error.retryable is True
    assert isinstance(error.__cause__, ConversationPersistenceError)
