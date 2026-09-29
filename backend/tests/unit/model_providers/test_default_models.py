from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    ClearDefaultModel,
    GetDefaultModels,
    SetDefaultModel,
)
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)


@dataclass
class FakePermissionChecker:
    allowed: bool = True
    permission: str | None = None

    async def has_permission(self, *, permission_key: str, **_kwargs: object) -> bool:
        self.permission = permission_key
        return self.allowed


class FakePersistence:
    def __init__(
        self,
        configuration: OrganizationModelProviderConfiguration | None = None,
    ) -> None:
        self.configuration = configuration
        self.load_calls = 0
        self.set_calls: list[tuple[UUID, ModelType, ConfiguredModelId | None]] = []
        self.error: Exception | None = None
        self.result = (
            DefaultModelSelection() if configuration is None else configuration.defaults
        )

    async def load_configuration(
        self, *, organization_public_id: UUID
    ) -> OrganizationModelProviderConfiguration | None:
        self.load_calls += 1
        return self.configuration

    async def set_default(
        self,
        *,
        organization_public_id: UUID,
        model_type: ModelType,
        model_id: ConfiguredModelId | None,
    ) -> DefaultModelSelection:
        self.set_calls.append((organization_public_id, model_type, model_id))
        if self.error is not None:
            raise self.error
        return self.result


def _configuration() -> tuple[
    OrganizationModelProviderConfiguration,
    ConfiguredModel,
]:
    organization_id = uuid4()
    provider = ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=ProviderType.OPENAI,
        display_name="OpenAI",
        settings=OpenAISettings(),
        enabled=True,
        credential_reference=CredentialReference(uuid4()),
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=datetime.now(UTC),
    )
    model = ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider.provider_id,
        provider_model_name="chat-model",
        display_name="Chat model",
        model_type=ModelType.CHAT,
        capabilities=frozenset({ModelCapability.STREAMING}),
    )
    return (
        OrganizationModelProviderConfiguration(
            organization_public_id=organization_id,
            providers=(provider,),
            models=(model,),
            defaults=DefaultModelSelection(chat=model.model_id),
        ),
        model,
    )


def test_get_returns_empty_selection_when_configuration_is_absent() -> None:
    persistence = FakePersistence()
    permission = FakePermissionChecker()
    service = GetDefaultModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permission,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.execute(
            organization_public_id=uuid4(),
            user_public_id=uuid4(),
        )
    )

    assert result == DefaultModelSelection()
    assert permission.permission == "model_providers.read"


def test_get_returns_authoritative_selection() -> None:
    configuration, _ = _configuration()
    service = GetDefaultModels(
        persistence=FakePersistence(configuration),  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.execute(
            organization_public_id=configuration.organization_public_id,
            user_public_id=uuid4(),
        )
    )

    assert result is configuration.defaults


@pytest.mark.parametrize("operation", ["get", "set", "clear"])
def test_denied_permission_stops_before_persistence(operation: str) -> None:
    persistence = FakePersistence()
    permission = FakePermissionChecker(allowed=False)
    organization_id = uuid4()
    if operation == "get":
        coroutine = GetDefaultModels(
            persistence=persistence,  # type: ignore[arg-type]
            permission_checker=permission,  # type: ignore[arg-type]
        ).execute(
            organization_public_id=organization_id,
            user_public_id=uuid4(),
        )
        expected_permission = "model_providers.read"
    elif operation == "set":
        coroutine = SetDefaultModel(
            persistence=persistence,  # type: ignore[arg-type]
            permission_checker=permission,  # type: ignore[arg-type]
        ).execute(
            organization_public_id=organization_id,
            user_public_id=uuid4(),
            model_type=ModelType.CHAT,
            model_public_id=uuid4(),
        )
        expected_permission = "model_providers.manage"
    else:
        coroutine = ClearDefaultModel(
            persistence=persistence,  # type: ignore[arg-type]
            permission_checker=permission,  # type: ignore[arg-type]
        ).execute(
            organization_public_id=organization_id,
            user_public_id=uuid4(),
            model_type=ModelType.CHAT,
        )
        expected_permission = "model_providers.manage"

    with pytest.raises(NexusError) as raised:
        asyncio.run(coroutine)

    assert raised.value.code is ErrorCode.FORBIDDEN
    assert permission.permission == expected_permission
    assert persistence.load_calls == 0
    assert persistence.set_calls == []


def test_set_returns_authoritative_selection_and_uses_public_model_id() -> None:
    configuration, model = _configuration()
    persistence = FakePersistence(configuration)
    permission = FakePermissionChecker()
    service = SetDefaultModel(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permission,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.execute(
            organization_public_id=configuration.organization_public_id,
            user_public_id=uuid4(),
            model_type=ModelType.CHAT,
            model_public_id=model.model_id.value,
        )
    )

    assert result is persistence.result
    assert permission.permission == "model_providers.manage"
    assert persistence.set_calls == [
        (
            configuration.organization_public_id,
            ModelType.CHAT,
            model.model_id,
        )
    ]


def test_clear_uses_same_persistence_operation_with_null_model() -> None:
    persistence = FakePersistence()
    service = ClearDefaultModel(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
    )
    organization_id = uuid4()

    result = asyncio.run(
        service.execute(
            organization_public_id=organization_id,
            user_public_id=uuid4(),
            model_type=ModelType.EMBEDDING,
        )
    )

    assert result is None
    assert persistence.set_calls == [(organization_id, ModelType.EMBEDDING, None)]


@pytest.mark.parametrize(
    ("error", "expected_code", "retryable"),
    [
        (ModelProviderConflictError("unsafe detail"), ErrorCode.CONFLICT, False),
        (
            ModelProviderConfigurationError("unsafe detail"),
            ErrorCode.CONFLICT,
            False,
        ),
        (ModelProviderReferenceError("unsafe detail"), ErrorCode.NOT_FOUND, False),
        (
            ModelProviderPersistenceError("unsafe detail"),
            ErrorCode.SERVICE_UNAVAILABLE,
            True,
        ),
    ],
)
def test_set_maps_persistence_errors_without_exposing_details(
    error: Exception,
    expected_code: ErrorCode,
    retryable: bool,
) -> None:
    persistence = FakePersistence()
    persistence.error = error
    service = SetDefaultModel(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
                model_type=ModelType.CHAT,
                model_public_id=uuid4(),
            )
        )

    assert raised.value.code is expected_code
    assert raised.value.retryable is retryable
    assert "unsafe detail" not in raised.value.message
