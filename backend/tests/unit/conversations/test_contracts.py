from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.conversations.domain import (
    Conversation,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def conversation(**overrides: object) -> Conversation:
    values: dict[str, object] = {
        "public_id": uuid4(),
        "organization_public_id": uuid4(),
        "created_by_user_public_id": uuid4(),
        "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP,
    }
    values.update(overrides)
    return Conversation(**values)  # type: ignore[arg-type]


def message(**overrides: object) -> Message:
    values: dict[str, object] = {
        "public_id": uuid4(),
        "conversation_public_id": uuid4(),
        "role": ConversationMessageRole.USER,
        "content": "Hello",
        "created_at": TIMESTAMP,
    }
    values.update(overrides)
    return Message(**values)  # type: ignore[arg-type]


def test_conversation_supports_standalone_scope() -> None:
    value = conversation()

    assert value.workspace_public_id is None
    assert value.project_public_id is None


def test_conversation_supports_workspace_scope() -> None:
    workspace_id = uuid4()

    value = conversation(workspace_public_id=workspace_id)

    assert value.workspace_public_id == workspace_id
    assert value.project_public_id is None


def test_conversation_supports_project_scope() -> None:
    workspace_id = uuid4()
    project_id = uuid4()

    value = conversation(
        workspace_public_id=workspace_id,
        project_public_id=project_id,
    )

    assert value.organization_public_id is not None
    assert value.created_by_user_public_id is not None
    assert value.workspace_public_id == workspace_id
    assert value.project_public_id == project_id


def test_project_scope_requires_workspace_scope() -> None:
    with pytest.raises(ValueError, match="workspace scope"):
        conversation(project_public_id=uuid4())


def test_conversation_supports_optional_title_and_is_frozen() -> None:
    value = conversation(title="Nexus work")

    assert value.title == "Nexus work"
    with pytest.raises(FrozenInstanceError):
        value.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "role",
    [
        ConversationMessageRole.SYSTEM,
        ConversationMessageRole.USER,
        ConversationMessageRole.ASSISTANT,
    ],
)
def test_message_supports_conversation_roles(role: ConversationMessageRole) -> None:
    value = message(role=role)

    assert value.role is role
    assert value.conversation_public_id is not None


@pytest.mark.parametrize("content", ["", " ", "\t\n"])
def test_message_rejects_empty_content(content: str) -> None:
    with pytest.raises(ValueError, match="content"):
        message(content=content)


def test_domain_contracts_reject_naive_timestamps() -> None:
    naive = TIMESTAMP.replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        conversation(created_at=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        message(created_at=naive)


def test_generation_supports_status_finish_reason_and_usage() -> None:
    value = Generation(
        public_id=uuid4(),
        conversation_public_id=uuid4(),
        user_message_public_id=uuid4(),
        assistant_message_public_id=uuid4(),
        model="gpt-test",
        status=GenerationStatus.COMPLETED,
        finish_reason=GenerationFinishReason.STOP,
        input_tokens=3,
        output_tokens=2,
        total_tokens=5,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    assert value.status is GenerationStatus.COMPLETED
    assert value.finish_reason is GenerationFinishReason.STOP
    assert value.input_tokens == 3
    assert value.output_tokens == 2
    assert value.total_tokens == 5


@pytest.mark.parametrize("field", ["started_at", "completed_at"])
def test_generation_rejects_naive_lifecycle_timestamps(field: str) -> None:
    values: dict[str, object] = {
        "public_id": uuid4(),
        "conversation_public_id": uuid4(),
        "user_message_public_id": uuid4(),
        "model": "gpt-test",
        "status": GenerationStatus.RUNNING,
        field: TIMESTAMP.replace(tzinfo=None),
    }

    with pytest.raises(ValueError, match="timezone-aware"):
        Generation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", list(GenerationStatus))
def test_generation_supports_required_statuses(status: GenerationStatus) -> None:
    value = Generation(
        public_id=uuid4(),
        conversation_public_id=uuid4(),
        user_message_public_id=uuid4(),
        model="gpt-test",
        status=status,
    )

    assert value.status is status


@pytest.mark.parametrize("model", ["", " ", "\t\n"])
def test_generation_rejects_empty_model(model: str) -> None:
    with pytest.raises(ValueError, match="model"):
        Generation(
            public_id=uuid4(),
            conversation_public_id=uuid4(),
            user_message_public_id=uuid4(),
            model=model,
            status=GenerationStatus.PENDING,
        )


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "total_tokens"])
def test_generation_rejects_negative_token_counts(field: str) -> None:
    values: dict[str, object] = {
        "public_id": uuid4(),
        "conversation_public_id": uuid4(),
        "user_message_public_id": uuid4(),
        "model": "gpt-test",
        "status": GenerationStatus.PENDING,
        field: -1,
    }

    with pytest.raises(ValueError, match=field):
        Generation(**values)  # type: ignore[arg-type]


def test_generation_rejects_blank_error_kind() -> None:
    with pytest.raises(ValueError, match="error_kind"):
        Generation(
            public_id=uuid4(),
            conversation_public_id=uuid4(),
            user_message_public_id=uuid4(),
            model="gpt-test",
            status=GenerationStatus.FAILED,
            error_kind=" ",
        )


def test_generation_is_frozen() -> None:
    value = Generation(
        public_id=uuid4(),
        conversation_public_id=uuid4(),
        user_message_public_id=uuid4(),
        model="gpt-test",
        status=GenerationStatus.PENDING,
    )

    with pytest.raises(FrozenInstanceError):
        value.status = GenerationStatus.RUNNING  # type: ignore[misc]
