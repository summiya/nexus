from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi.testclient import TestClient

from nexus.authentication.api.security import get_current_auth_context
from nexus.authentication.tokens import AuthTokenContext
from nexus.config.settings import Settings
from nexus.conversations.api.dependencies import get_stream_conversation_message
from nexus.conversations.application.events import (
    ConversationEvent,
    GenerationCompleted,
    GenerationStarted,
    MessageDelta,
)
from nexus.conversations.application.stream_message import (
    StreamConversationMessageRequest,
)
from nexus.conversations.domain import GenerationFinishReason
from nexus.errors import ErrorCode, NexusError
from nexus.main import create_app


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
    app = create_app(settings)
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
    app = create_app(settings)
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
    app = create_app(settings)
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
    app = create_app(settings)
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
