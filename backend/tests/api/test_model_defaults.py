from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.security import get_current_auth_context
from nexus.authentication.tokens import AuthTokenContext
from nexus.errors.handlers import register_exception_handlers
from nexus.model_providers.api.defaults import router
from nexus.model_providers.api.dependencies import (
    get_default_model_clearer,
    get_default_model_getter,
    get_default_model_setter,
)
from nexus.model_providers.domain import (
    ConfiguredModelId,
    DefaultModelSelection,
    ModelType,
)


class FakeGetter:
    def __init__(self, result: DefaultModelSelection) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID]] = []

    async def execute(
        self, *, organization_public_id: UUID, user_public_id: UUID
    ) -> DefaultModelSelection:
        self.calls.append((organization_public_id, user_public_id))
        return self.result


class FakeSetter:
    def __init__(self, result: DefaultModelSelection) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID, ModelType, UUID]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        model_type: ModelType,
        model_public_id: UUID,
    ) -> DefaultModelSelection:
        self.calls.append(
            (
                organization_public_id,
                user_public_id,
                model_type,
                model_public_id,
            )
        )
        return self.result


class FakeClearer:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, ModelType]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        model_type: ModelType,
    ) -> None:
        self.calls.append((organization_public_id, user_public_id, model_type))


def _app() -> tuple[FastAPI, UUID, UUID]:
    organization_id = uuid4()
    user_id = uuid4()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_id,
        organization_public_id=organization_id,
        session_public_id=uuid4(),
    )
    return app, organization_id, user_id


def test_get_returns_all_null_slots_for_empty_selection() -> None:
    app, organization_id, user_id = _app()
    service = FakeGetter(DefaultModelSelection())
    app.dependency_overrides[get_default_model_getter] = lambda: service

    with TestClient(app) as client:
        response = client.get("/api/v1/model-defaults")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"chat": None, "embedding": None, "reranker": None}
    assert service.calls == [(organization_id, user_id)]


def test_get_exposes_only_public_configured_model_ids() -> None:
    app, _, _ = _app()
    defaults = DefaultModelSelection(
        chat=ConfiguredModelId(uuid4()),
        embedding=ConfiguredModelId(uuid4()),
        reranker=ConfiguredModelId(uuid4()),
    )
    app.dependency_overrides[get_default_model_getter] = lambda: FakeGetter(defaults)

    with TestClient(app) as client:
        response = client.get("/api/v1/model-defaults")

    assert response.json() == {
        "chat": str(defaults.chat.value),  # type: ignore[union-attr]
        "embedding": str(defaults.embedding.value),  # type: ignore[union-attr]
        "reranker": str(defaults.reranker.value),  # type: ignore[union-attr]
    }
    for forbidden in (
        "credential",
        "provider",
        "organization",
        "internal_id",
        "secret",
    ):
        assert forbidden not in response.text


def test_put_uses_path_type_trusted_context_and_returns_complete_selection() -> None:
    app, organization_id, user_id = _app()
    model_id = uuid4()
    defaults = DefaultModelSelection(chat=ConfiguredModelId(model_id))
    service = FakeSetter(defaults)
    app.dependency_overrides[get_default_model_setter] = lambda: service

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/model-defaults/chat",
            json={"model_public_id": str(model_id)},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "chat": str(model_id),
        "embedding": None,
        "reranker": None,
    }
    assert service.calls == [(organization_id, user_id, ModelType.CHAT, model_id)]


def test_delete_returns_204_and_clears_only_requested_type() -> None:
    app, organization_id, user_id = _app()
    service = FakeClearer()
    app.dependency_overrides[get_default_model_clearer] = lambda: service

    with TestClient(app) as client:
        response = client.delete("/api/v1/model-defaults/embedding")

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [(organization_id, user_id, ModelType.EMBEDDING)]


def test_invalid_model_type_is_rejected_before_service() -> None:
    app, _, _ = _app()
    service = FakeSetter(DefaultModelSelection())
    app.dependency_overrides[get_default_model_setter] = lambda: service

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/model-defaults/image",
            json={"model_public_id": str(uuid4())},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert service.calls == []


def test_invalid_model_uuid_is_rejected_before_service() -> None:
    app, _, _ = _app()
    service = FakeSetter(DefaultModelSelection())
    app.dependency_overrides[get_default_model_setter] = lambda: service

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/model-defaults/chat",
            json={"model_public_id": "not-a-uuid"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert service.calls == []
