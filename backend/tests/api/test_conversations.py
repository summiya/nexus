from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.security import get_current_auth_context
from nexus.authentication.tokens import AuthTokenContext
from nexus.config.settings import Settings
from nexus.conversations.api.dependencies import (
    get_conversation_messages,
    get_list_conversations,
    get_stream_conversation_message,
)
from nexus.conversations.application.events import (
    ConversationEvent,
    GenerationCompleted,
    GenerationStarted,
    MessageDelta,
)
from nexus.conversations.application.stream_message import (
    StreamConversationMessageRequest,
)
from nexus.conversations.domain import (
    Conversation,
    ConversationGenerationMetadata,
    ConversationMessageHistoryItem,
    ConversationMessageRole,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.errors import ErrorCode, NexusError
from nexus.files.ports import ObjectStorage
from nexus.main import create_app

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


class FakeListConversationsService:
    def __init__(self, conversations: tuple[Conversation, ...] = ()) -> None:
        self.conversations = conversations
        self.calls: list[tuple[UUID, UUID]] = []
        self.error: NexusError | None = None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> tuple[Conversation, ...]:
        self.calls.append((organization_public_id, user_public_id))
        if self.error is not None:
            raise self.error
        return self.conversations


class FakeGetConversationMessagesService:
    def __init__(
        self,
        history: tuple[ConversationMessageHistoryItem, ...] = (),
    ) -> None:
        self.history = history
        self.calls: list[tuple[UUID, UUID, UUID]] = []
        self.error: NexusError | None = None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[ConversationMessageHistoryItem, ...]:
        self.calls.append(
            (
                organization_public_id,
                user_public_id,
                conversation_public_id,
            )
        )
        if self.error is not None:
            raise self.error
        return self.history


def _conversation(*, created_at: datetime, title: str | None) -> Conversation:
    return Conversation(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        title=title,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=1),
    )


def _message(
    *,
    conversation_public_id: UUID,
    role: ConversationMessageRole,
    content: str,
    created_at: datetime,
) -> Message:
    return Message(
        public_id=uuid4(),
        conversation_public_id=conversation_public_id,
        role=role,
        content=content,
        created_at=created_at,
    )


def _history_item(
    message: Message,
    generation: ConversationGenerationMetadata | None = None,
) -> ConversationMessageHistoryItem:
    return ConversationMessageHistoryItem(
        message=message,
        generation=generation,
    )


def _generation_metadata(
    *,
    status: GenerationStatus = GenerationStatus.COMPLETED,
    error_kind: str | None = None,
) -> ConversationGenerationMetadata:
    return ConversationGenerationMetadata(
        public_id=uuid4(),
        model="gpt-test",
        status=status,
        finish_reason=(
            GenerationFinishReason.STOP
            if status is GenerationStatus.COMPLETED
            else None
        ),
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP + timedelta(seconds=1),
        error_kind=error_kind,
    )


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
    )


def _create_test_app(settings: Settings) -> FastAPI:
    return create_app(
        settings,
        object_storage=Mock(spec=ObjectStorage),
    )


def _list_test_app(
    service: FakeListConversationsService,
    *,
    organization_public_id: UUID,
    user_public_id: UUID,
) -> FastAPI:
    app = _create_test_app(_settings())
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_public_id,
        organization_public_id=organization_public_id,
        session_public_id=uuid4(),
    )
    app.dependency_overrides[get_list_conversations] = lambda: service
    return app


def _messages_test_app(
    service: FakeGetConversationMessagesService,
    *,
    organization_public_id: UUID,
    user_public_id: UUID,
) -> FastAPI:
    app = _create_test_app(_settings())
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_public_id,
        organization_public_id=organization_public_id,
        session_public_id=uuid4(),
    )
    app.dependency_overrides[get_conversation_messages] = lambda: service
    return app


def test_list_conversations_returns_authenticated_users_conversations() -> None:
    conversation = _conversation(created_at=TIMESTAMP, title="Nexus work")
    service = FakeListConversationsService((conversation,))
    app = _list_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert response.status_code == 200
    assert response.json()["items"][0]["public_id"] == str(conversation.public_id)
    assert response.json()["items"][0]["title"] == "Nexus work"


def test_list_conversations_exposes_only_the_intended_fields() -> None:
    conversation = _conversation(created_at=TIMESTAMP, title=None)
    service = FakeListConversationsService((conversation,))
    app = _list_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert set(response.json()["items"][0]) == {
        "public_id",
        "title",
        "created_at",
        "updated_at",
    }


def test_list_conversations_preserves_application_service_ordering() -> None:
    newest = _conversation(
        created_at=TIMESTAMP + timedelta(minutes=1),
        title="Newest",
    )
    oldest = _conversation(created_at=TIMESTAMP, title="Oldest")
    service = FakeListConversationsService((newest, oldest))
    app = _list_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert [item["public_id"] for item in response.json()["items"]] == [
        str(newest.public_id),
        str(oldest.public_id),
    ]


def test_list_conversations_returns_empty_items() -> None:
    service = FakeListConversationsService()
    app = _list_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_list_conversations_passes_only_trusted_authentication_scope() -> None:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    service = FakeListConversationsService()
    app = _list_test_app(
        service,
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert response.status_code == 200
    assert service.calls == [(organization_public_id, user_public_id)]


def test_list_conversations_returns_safe_application_failure() -> None:
    service = FakeListConversationsService()
    service.error = NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "The conversations could not be retrieved.",
        retryable=True,
    )
    app = _list_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "The conversations could not be retrieved.",
        "request_id": response.headers["X-Request-ID"],
    }


def test_get_conversation_messages_returns_persisted_history() -> None:
    conversation_public_id = uuid4()
    message = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.USER,
        content="Hello",
        created_at=TIMESTAMP,
    )
    service = FakeGetConversationMessagesService((_history_item(message),))
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "public_id": str(message.public_id),
        "role": "user",
        "content": "Hello",
        "created_at": "2026-01-01T00:00:00Z",
        "generation": None,
    }


def test_get_conversation_messages_exposes_only_the_intended_fields() -> None:
    conversation_public_id = uuid4()
    message = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Welcome",
        created_at=TIMESTAMP,
    )
    service = FakeGetConversationMessagesService((_history_item(message),))
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert set(response.json()["items"][0]) == {
        "public_id",
        "role",
        "content",
        "created_at",
        "generation",
    }
    assert response.json()["items"][0]["generation"] is None


def test_get_conversation_messages_returns_typed_generation_metadata() -> None:
    conversation_public_id = uuid4()
    message = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Welcome",
        created_at=TIMESTAMP + timedelta(seconds=1),
    )
    generation = _generation_metadata()
    service = FakeGetConversationMessagesService((_history_item(message, generation),))
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 200
    generation_body = response.json()["items"][0]["generation"]
    assert set(generation_body) == {
        "public_id",
        "model",
        "status",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "started_at",
        "completed_at",
        "error_kind",
    }
    assert generation_body == {
        "public_id": str(generation.public_id),
        "model": "gpt-test",
        "status": "completed",
        "finish_reason": "stop",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:01Z",
        "error_kind": None,
    }


def test_get_conversation_messages_serializes_safe_generation_error_kind() -> None:
    conversation_public_id = uuid4()
    message = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Partial response",
        created_at=TIMESTAMP,
    )
    generation = _generation_metadata(
        status=GenerationStatus.FAILED,
        error_kind="stream_processing_failure",
    )
    service = FakeGetConversationMessagesService((_history_item(message, generation),))
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    generation_body = response.json()["items"][0]["generation"]
    assert generation_body["status"] == "failed"
    assert generation_body["finish_reason"] is None
    assert generation_body["error_kind"] == "stream_processing_failure"


def test_get_conversation_messages_returns_null_generation_for_system_message() -> None:
    conversation_public_id = uuid4()
    message = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.SYSTEM,
        content="System instruction",
        created_at=TIMESTAMP,
    )
    service = FakeGetConversationMessagesService((_history_item(message),))
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["generation"] is None


def test_get_conversation_messages_returns_empty_items() -> None:
    conversation_public_id = uuid4()
    service = FakeGetConversationMessagesService()
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_get_conversation_messages_preserves_application_ordering() -> None:
    conversation_public_id = uuid4()
    oldest = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.USER,
        content="First",
        created_at=TIMESTAMP,
    )
    newest = _message(
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole.ASSISTANT,
        content="Second",
        created_at=TIMESTAMP + timedelta(minutes=1),
    )
    service = FakeGetConversationMessagesService(
        (_history_item(oldest), _history_item(newest))
    )
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert [item["public_id"] for item in response.json()["items"]] == [
        str(oldest.public_id),
        str(newest.public_id),
    ]


def test_get_conversation_messages_passes_trusted_authentication_scope() -> None:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    conversation_public_id = uuid4()
    service = FakeGetConversationMessagesService()
    app = _messages_test_app(
        service,
        organization_public_id=organization_public_id,
        user_public_id=user_public_id,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 200
    assert service.calls == [
        (organization_public_id, user_public_id, conversation_public_id)
    ]


def test_get_conversation_messages_returns_safe_unknown_conversation_error() -> None:
    conversation_public_id = uuid4()
    service = FakeGetConversationMessagesService()
    service.error = NexusError(
        ErrorCode.NOT_FOUND,
        "The requested resource was not found.",
    )
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "The requested resource was not found.",
        "request_id": response.headers["X-Request-ID"],
    }


def test_get_conversation_messages_hides_inaccessible_standalone_conversation() -> None:
    conversation_public_id = uuid4()
    service = FakeGetConversationMessagesService()
    service.error = NexusError(
        ErrorCode.NOT_FOUND,
        "The requested resource was not found.",
    )
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "The requested resource was not found.",
        "request_id": response.headers["X-Request-ID"],
    }


def test_get_conversation_messages_returns_safe_workspace_authorization_error() -> None:
    conversation_public_id = uuid4()
    service = FakeGetConversationMessagesService()
    service.error = NexusError(
        ErrorCode.FORBIDDEN,
        "You are not allowed to perform this action.",
    )
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "FORBIDDEN",
        "message": "You are not allowed to perform this action.",
        "request_id": response.headers["X-Request-ID"],
    }


def test_get_conversation_messages_returns_safe_application_failure() -> None:
    conversation_public_id = uuid4()
    service = FakeGetConversationMessagesService()
    service.error = NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "The conversation messages could not be retrieved.",
        retryable=True,
    )
    app = _messages_test_app(
        service,
        organization_public_id=uuid4(),
        user_public_id=uuid4(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_public_id}/messages"
        )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "The conversation messages could not be retrieved.",
        "request_id": response.headers["X-Request-ID"],
    }


class FakePreparedStream:
    def __init__(self) -> None:
        self.conversation_id = uuid4()
        self.generation_id = uuid4()
        self.assistant_id = uuid4()

    def __aiter__(self) -> AsyncIterator[ConversationEvent]:
        async def events() -> AsyncIterator[ConversationEvent]:
            yield GenerationStarted(
                self.conversation_id, self.generation_id, "gpt-test"
            )
            yield MessageDelta(self.conversation_id, self.generation_id, "Hello")
            yield GenerationCompleted(
                self.conversation_id,
                self.generation_id,
                self.assistant_id,
                finish_reason=GenerationFinishReason.STOP,
            )

        return events()

    async def aclose(self) -> None:
        return None


class FakeConversationStreamService:
    def __init__(self) -> None:
        self.requests: list[StreamConversationMessageRequest] = []

    async def prepare(
        self,
        request: StreamConversationMessageRequest,
    ) -> FakePreparedStream:
        self.requests.append(request)
        return FakePreparedStream()


class FailingPreflightService:
    async def prepare(self, request: object) -> FakePreparedStream:
        del request
        raise NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "The language model service is unavailable.",
            retryable=True,
        )


class ConflictingPreparationService:
    async def prepare(self, request: object) -> FakePreparedStream:
        del request
        raise NexusError(
            ErrorCode.CONFLICT,
            "A generation is already in progress for this conversation.",
        )


def test_message_endpoint_uses_native_sse_and_maps_application_events() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
    )
    app = _create_test_app(settings)
    organization_id = uuid4()
    user_id = uuid4()
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_id,
        organization_public_id=organization_id,
        session_public_id=uuid4(),
    )
    service = FakeConversationStreamService()
    app.dependency_overrides[get_stream_conversation_message] = lambda: service
    idempotency_key = uuid4()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/conversations/{uuid4()}/messages",
            json={"content": "Hello", "model": "gpt-test"},
            headers={"Idempotency-Key": str(idempotency_key)},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: generation.started" in response.text
    assert "event: message.delta" in response.text
    assert "event: generation.completed" in response.text
    assert "event: generation.error" not in response.text
    assert service.requests[0].idempotency_key == idempotency_key


def test_message_endpoint_rejects_an_invalid_idempotency_key() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
    )
    app = _create_test_app(settings)
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    service = FakeConversationStreamService()
    app.dependency_overrides[get_stream_conversation_message] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/conversations/{uuid4()}/messages",
            json={"content": "Hello", "model": "gpt-test"},
            headers={"Idempotency-Key": "not-a-uuid"},
        )

    assert response.status_code == 422
    assert service.requests == []


def test_message_endpoint_returns_http_error_when_preflight_fails() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
    )
    app = _create_test_app(settings)
    organization_id = uuid4()
    user_id = uuid4()
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_id,
        organization_public_id=organization_id,
        session_public_id=uuid4(),
    )
    app.dependency_overrides[get_stream_conversation_message] = lambda: (
        FailingPreflightService()
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/conversations/{uuid4()}/messages",
            json={"content": "Hello", "model": "gpt-test"},
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert "text/event-stream" not in response.headers["content-type"]
    assert "generation.started" not in response.text


def test_message_endpoint_returns_safe_conflict_before_streaming() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
    )
    app = _create_test_app(settings)
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=uuid4(),
        session_public_id=uuid4(),
    )
    app.dependency_overrides[get_stream_conversation_message] = lambda: (
        ConflictingPreparationService()
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/conversations/{uuid4()}/messages",
            json={"content": "Hello", "model": "gpt-test"},
        )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "CONFLICT",
        "message": "A generation is already in progress for this conversation.",
        "request_id": response.headers["X-Request-ID"],
    }
    assert "text/event-stream" not in response.headers["content-type"]
