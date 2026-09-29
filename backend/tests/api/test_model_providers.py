from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.security import get_current_auth_context
from nexus.authentication.tokens import AuthTokenContext
from nexus.config.settings import Settings
from nexus.files.ports import ObjectStorage
from nexus.main import create_app
from nexus.model_providers.api.dependencies import (
    get_provider_catalog,
    get_provider_creator,
    get_provider_credential_setter,
    get_provider_deleter,
    get_provider_enabled_setter,
    get_provider_list,
    get_provider_model_discovery,
    get_provider_updater,
    get_provider_validator,
)
from nexus.model_providers.application import ProviderCatalogItem
from nexus.model_providers.domain import (
    ConfiguredProvider,
    CredentialReference,
    ModelCandidate,
    ModelCapability,
    ModelType,
    OpenAICompatibleSettings,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderType,
    ProviderValidationStatus,
)


class FakeCatalog:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    async def execute(
        self, *, organization_public_id: UUID, user_public_id: UUID
    ) -> tuple[ProviderCatalogItem, ...]:
        self.calls.append((organization_public_id, user_public_id))
        return (
            ProviderCatalogItem(
                ProviderType.OPENAI_COMPATIBLE,
                "OpenAI-compatible",
                ("base_url",),
            ),
        )


class FakeList:
    def __init__(self, provider: ConfiguredProvider) -> None:
        self.provider = provider
        self.calls: list[tuple[UUID, UUID]] = []

    async def execute(
        self, *, organization_public_id: UUID, user_public_id: UUID
    ) -> tuple[ConfiguredProvider, ...]:
        self.calls.append((organization_public_id, user_public_id))
        return (self.provider,)


class FakeDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
    ) -> tuple[ModelCandidate, ...]:
        self.calls.append((organization_public_id, user_public_id, provider_public_id))
        return (
            ModelCandidate(
                provider_model_name="gpt-test",
                display_name="GPT Test",
                model_type=ModelType.CHAT,
                capabilities=frozenset(
                    {ModelCapability.TOOLS, ModelCapability.STREAMING}
                ),
            ),
        )


class FakeMutation:
    def __init__(self, provider: ConfiguredProvider, operation: str) -> None:
        self.provider = provider
        self.operation = operation
        self.secret: ProviderCredentialSecret | None = None
        self.calls: list[tuple[str, UUID, UUID]] = []
        self.last_values: dict[str, object] = {}

    async def execute(self, **values: object) -> ConfiguredProvider | None:
        self.last_values = values
        organization_public_id = values["organization_public_id"]
        user_public_id = values["user_public_id"]
        assert isinstance(organization_public_id, UUID)
        assert isinstance(user_public_id, UUID)
        self.calls.append((self.operation, organization_public_id, user_public_id))
        secret = values.get("secret")
        if isinstance(secret, ProviderCredentialSecret):
            self.secret = secret
        if self.operation == "delete":
            return None
        return self.provider


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key="bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE",
    )


def _provider(organization_id: UUID) -> ConfiguredProvider:
    return ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        display_name="Private provider",
        settings=OpenAICompatibleSettings(base_url="https://models.example.com"),
        enabled=True,
        credential_reference=CredentialReference(uuid4()),
    )


def _app() -> tuple[FastAPI, UUID, UUID, ConfiguredProvider]:
    organization_id = uuid4()
    user_id = uuid4()
    provider = _provider(organization_id)
    app = create_app(_settings(), object_storage=Mock(spec=ObjectStorage))
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_id,
        organization_public_id=organization_id,
        session_public_id=uuid4(),
    )
    return app, organization_id, user_id, provider


def test_catalog_uses_trusted_auth_context_and_returns_safe_contract() -> None:
    app, organization_id, user_id, _ = _app()
    service = FakeCatalog()
    app.dependency_overrides[get_provider_catalog] = lambda: service

    with TestClient(app) as client:
        response = client.get("/api/v1/model-providers/catalog")

    assert response.status_code == 200
    assert service.calls == [(organization_id, user_id)]
    assert response.json() == {
        "items": [
            {
                "provider_type": "openai_compatible",
                "display_name": "OpenAI-compatible",
                "required_settings": ["base_url"],
            }
        ]
    }


def test_provider_reads_mask_all_credential_storage_details() -> None:
    app, organization_id, user_id, provider = _app()
    service = FakeList(provider)
    app.dependency_overrides[get_provider_list] = lambda: service

    with TestClient(app) as client:
        response = client.get("/api/v1/model-providers")

    assert response.status_code == 200
    assert service.calls == [(organization_id, user_id)]
    assert response.json() == {
        "items": [
            {
                "public_id": str(provider.provider_id.value),
                "provider_type": "openai_compatible",
                "display_name": "Private provider",
                "settings": {"base_url": "https://models.example.com"},
                "enabled": True,
                "credential_configured": True,
                "validation_status": "unvalidated",
                "last_validated_at": None,
            }
        ]
    }
    for forbidden in ("credential_reference", "npc-v1", "secret", "api-key"):
        assert forbidden not in response.text


def test_model_discovery_uses_trusted_context_and_returns_safe_contract() -> None:
    app, organization_id, user_id, provider = _app()
    service = FakeDiscovery()
    app.dependency_overrides[get_provider_model_discovery] = lambda: service

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/model-providers/{provider.provider_id.value}/models"
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert service.calls == [(organization_id, user_id, provider.provider_id.value)]
    assert response.json() == {
        "items": [
            {
                "provider_model_name": "gpt-test",
                "display_name": "GPT Test",
                "model_type": "chat",
                "capabilities": ["streaming", "tools"],
                "embedding_dimension": None,
            }
        ]
    }
    for forbidden in (
        "credential_reference",
        "credential",
        "organization_public_id",
        "provider_public_id",
    ):
        assert forbidden not in response.text


def test_update_dto_does_not_accept_provider_type() -> None:
    app, _, _, provider = _app()

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/model-providers/{provider.provider_id.value}",
            json={
                "provider_type": "openai",
                "display_name": "Changed",
                "settings": {"base_url": "https://models.example.com"},
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_update_requires_at_least_one_changed_field() -> None:
    app, _, _, provider = _app()

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/model-providers/{provider.provider_id.value}",
            json={},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_display_name_only_update_omits_settings_from_application_change() -> None:
    app, _, _, provider = _app()
    service = FakeMutation(provider, "update")
    app.dependency_overrides[get_provider_updater] = lambda: service

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/model-providers/{provider.provider_id.value}",
            json={"display_name": "Renamed"},
        )

    assert response.status_code == 200
    assert service.last_values["display_name"] == "Renamed"
    assert service.last_values["settings"] is None


def test_provider_mutation_routes_use_trusted_auth_context() -> None:
    app, organization_id, user_id, provider = _app()
    services = {
        "create": FakeMutation(provider, "create"),
        "update": FakeMutation(provider, "update"),
        "enabled": FakeMutation(provider, "enabled"),
        "delete": FakeMutation(provider, "delete"),
    }
    app.dependency_overrides[get_provider_creator] = lambda: services["create"]
    app.dependency_overrides[get_provider_updater] = lambda: services["update"]
    app.dependency_overrides[get_provider_enabled_setter] = lambda: services["enabled"]
    app.dependency_overrides[get_provider_deleter] = lambda: services["delete"]
    provider_path = f"/api/v1/model-providers/{provider.provider_id.value}"

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/model-providers",
            json={
                "provider_type": "openai_compatible",
                "display_name": "Private provider",
                "settings": {"base_url": "https://models.example.com"},
                "enabled": True,
            },
        )
        update_response = client.put(
            provider_path,
            json={
                "display_name": "Private provider",
                "settings": {"base_url": "https://models.example.com"},
            },
        )
        enabled_response = client.patch(
            f"{provider_path}/enabled",
            json={"enabled": False},
        )
        delete_response = client.delete(provider_path)

    assert create_response.status_code == 201
    assert update_response.status_code == 200
    assert enabled_response.status_code == 200
    assert delete_response.status_code == 204
    assert [call for service in services.values() for call in service.calls] == [
        ("create", organization_id, user_id),
        ("update", organization_id, user_id),
        ("enabled", organization_id, user_id),
        ("delete", organization_id, user_id),
    ]


def test_validate_provider_uses_trusted_context_and_returns_safe_result() -> None:
    app, organization_id, user_id, provider = _app()
    validated = replace(
        provider,
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=datetime(2026, 9, 29, 12, 30, tzinfo=UTC),
    )
    service = FakeMutation(validated, "validate")
    app.dependency_overrides[get_provider_validator] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/model-providers/{provider.provider_id.value}/validate"
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "status": "valid",
        "last_validated_at": "2026-09-29T12:30:00Z",
    }
    assert service.calls == [("validate", organization_id, user_id)]
    assert service.last_values["provider_public_id"] == provider.provider_id.value
    for forbidden in (
        "credential_reference",
        "secret",
        "api-key",
        "npc-v1",
    ):
        assert forbidden not in response.text


def test_credential_endpoint_is_write_only_and_does_not_log_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, _, _, provider = _app()
    service = FakeMutation(provider, "credential")
    app.dependency_overrides[get_provider_credential_setter] = lambda: service
    plaintext = "submitted-provider-secret"

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/model-providers/{provider.provider_id.value}/credential",
            json={"credential": plaintext},
        )

    assert response.status_code == 200
    assert response.json() == {"credential_configured": True}
    assert service.secret is not None
    assert service.secret.reveal() == plaintext
    assert plaintext not in response.text
    assert plaintext not in caplog.text


def test_oversized_credential_returns_safe_422_without_reflection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, _, _, provider = _app()
    secret = "x" * (16 * 1024 + 1)

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/model-providers/{provider.provider_id.value}/credential",
            json={"credential": secret},
        )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "The request validation failed.",
        "request_id": response.headers["X-Request-ID"],
    }
    assert secret not in response.text
    assert secret not in caplog.text


def test_utf8_oversized_credential_returns_safe_422_without_reflection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, _, _, provider = _app()
    secret = "é" * 9000

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/model-providers/{provider.provider_id.value}/credential",
            json={"credential": secret},
        )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == (
        "Provider credential secret is invalid."
    )
    assert secret not in response.text
    assert secret not in caplog.text
