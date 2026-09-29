from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.dependencies import get_access_authentication_service
from nexus.authentication.api.security import get_current_auth_context
from nexus.authentication.tokens import AuthTokenContext
from nexus.errors import ErrorCode, NexusError
from nexus.errors.handlers import register_exception_handlers
from nexus.model_providers.api.chat_models import router
from nexus.model_providers.api.dependencies import get_selectable_chat_model_list
from nexus.model_providers.application import (
    SelectableChatModel,
    SelectableChatModels,
)
from nexus.model_providers.domain import ConfiguredModelId, ProviderType


class FakeService:
    def __init__(
        self,
        result: SelectableChatModels,
        *,
        error: NexusError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[UUID] = []

    async def execute(self, *, organization_public_id: UUID) -> SelectableChatModels:
        self.calls.append(organization_public_id)
        if self.error is not None:
            raise self.error
        return self.result


def _app(
    result: SelectableChatModels,
) -> tuple[FastAPI, FakeService, UUID]:
    organization_id = uuid4()
    service = FakeService(result)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_selectable_chat_model_list] = lambda: service
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=uuid4(),
        organization_public_id=organization_id,
        session_public_id=uuid4(),
    )
    return app, service, organization_id


def test_returns_safe_tenant_scoped_chat_model_selection_contract() -> None:
    model_id = ConfiguredModelId(uuid4())
    result = SelectableChatModels(
        items=(
            SelectableChatModel(
                model_id=model_id,
                display_name="GPT-5",
                provider_type=ProviderType.OPENAI,
                provider_display_name="OpenAI",
            ),
        ),
        default_model_id=model_id,
    )
    app, service, organization_id = _app(result)

    with TestClient(app) as client:
        response = client.get("/api/v1/chat-models")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "items": [
            {
                "public_id": str(model_id.value),
                "display_name": "GPT-5",
                "provider_type": "openai",
                "provider_display_name": "OpenAI",
            }
        ],
        "default_model_public_id": str(model_id.value),
    }
    assert service.calls == [organization_id]
    for forbidden in (
        "credential",
        "provider_model_name",
        "endpoint",
        "base_url",
        "settings",
        "api_version",
        "secret",
    ):
        assert forbidden not in response.text


def test_empty_configuration_returns_an_empty_selection() -> None:
    app, _, _ = _app(SelectableChatModels(items=(), default_model_id=None))

    with TestClient(app) as client:
        response = client.get("/api/v1/chat-models")

    assert response.status_code == 200
    assert response.json() == {"items": [], "default_model_public_id": None}


def test_unauthenticated_request_is_rejected_before_selector_service() -> None:
    result = SelectableChatModels(items=(), default_model_id=None)
    service = FakeService(result)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_selectable_chat_model_list] = lambda: service
    app.dependency_overrides[get_access_authentication_service] = lambda: object()

    with TestClient(app) as client:
        response = client.get("/api/v1/chat-models")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHORIZED.value
    assert service.calls == []


def test_service_unavailable_uses_standard_safe_error_envelope() -> None:
    result = SelectableChatModels(items=(), default_model_id=None)
    app, service, _ = _app(result)
    service.error = NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "Chat model selection is temporarily unavailable.",
        retryable=True,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/chat-models")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "Chat model selection is temporarily unavailable.",
            "request_id": None,
        }
    }
