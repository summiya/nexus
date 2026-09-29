from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    ListConfiguredModels,
    RegisterConfiguredModels,
)
from nexus.model_providers.application._provider_model_discovery import (
    ProviderDiscoveryResult,
)
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredModel,
    ConfiguredModelId,
    CredentialReference,
    GeminiSettings,
    ModelCandidate,
    ModelCapability,
    ModelType,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.domain.contracts import ConfiguredProvider
from nexus.model_providers.ports import ModelProviderConflictError


@dataclass
class AllowPermission:
    permission: str | None = None

    async def has_permission(self, *, permission_key: str, **_kwargs: object) -> bool:
        self.permission = permission_key
        return True


@dataclass
class DenyPermission:
    permission: str | None = None

    async def has_permission(self, *, permission_key: str, **_kwargs: object) -> bool:
        self.permission = permission_key
        return False


class FakePersistence:
    def __init__(self, provider: ConfiguredProvider) -> None:
        self.provider = provider
        self.models: tuple[ConfiguredModel, ...] = ()
        self.discovered_calls = 0
        self.manual_calls = 0
        self.error: Exception | None = None

    async def load_configuration(
        self, *, organization_public_id: UUID
    ) -> OrganizationModelProviderConfiguration:
        return OrganizationModelProviderConfiguration(
            organization_public_id=organization_public_id,
            providers=(self.provider,),
            models=self.models,
        )

    async def create_discovered_models(
        self, *, models: tuple[ConfiguredModel, ...], **_kwargs: object
    ) -> None:
        self.discovered_calls += 1
        if self.error is not None:
            raise self.error
        self.models = models

    async def create_manual_model(
        self, *, model: ConfiguredModel, **_kwargs: object
    ) -> None:
        self.manual_calls += 1
        if self.error is not None:
            raise self.error
        self.models = (model,)


class FakeDiscovery:
    def __init__(
        self, provider: ConfiguredProvider, candidates: tuple[ModelCandidate, ...]
    ) -> None:
        self.provider = provider
        self.candidates = candidates
        self.calls = 0

    async def discover(self, **_kwargs: object) -> ProviderDiscoveryResult:
        self.calls += 1
        return ProviderDiscoveryResult(self.provider, self.candidates)


def _provider(provider_type: ProviderType = ProviderType.OPENAI) -> ConfiguredProvider:
    settings = {
        ProviderType.OPENAI: OpenAISettings(),
        ProviderType.ANTHROPIC: AnthropicSettings(),
        ProviderType.AZURE_OPENAI: AzureOpenAISettings(
            endpoint="https://models.openai.azure.com",
            api_version="2026-01-01",
        ),
        ProviderType.GEMINI: GeminiSettings(),
        ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleSettings(
            base_url="https://models.example.com"
        ),
    }[provider_type]
    return ConfiguredProvider(
        organization_public_id=uuid4(),
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=provider_type,
        display_name="Provider",
        settings=settings,
        enabled=True,
        credential_reference=CredentialReference(uuid4()),
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=datetime.now(UTC),
    )


def _candidate(name: str, display_name: str) -> ModelCandidate:
    return ModelCandidate(
        provider_model_name=name,
        display_name=display_name,
        model_type=ModelType.CHAT,
        capabilities=frozenset({ModelCapability.STREAMING}),
    )


def test_discovered_batch_uses_one_discovery_and_preserves_request_order() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(
        provider,
        (_candidate("second", "Second"), _candidate("first", "First")),
    )
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.register_discovered(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
            provider_model_names=("first", "second"),
        )
    )

    assert discovery.calls == 1
    assert persistence.discovered_calls == 1
    assert [item.model.provider_model_name for item in result] == ["first", "second"]
    assert all(item.model.enabled for item in result)


def test_exactly_fifty_discovered_models_use_one_discovery_and_atomic_write() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    requested_names = tuple(f"model-{index:02d}" for index in range(50))
    discovery = FakeDiscovery(
        provider,
        tuple(
            _candidate(name, f"Model {index:02d}")
            for index, name in reversed(tuple(enumerate(requested_names)))
        ),
    )
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.register_discovered(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
            provider_model_names=requested_names,
        )
    )

    assert discovery.calls == 1
    assert persistence.discovered_calls == 1
    assert tuple(item.model.provider_model_name for item in result) == requested_names
    assert tuple(model.provider_model_name for model in persistence.models) == (
        requested_names
    )


@pytest.mark.parametrize(
    "names",
    [(), ("same", "same"), tuple(f"model-{index}" for index in range(51))],
)
def test_invalid_discovered_batch_is_rejected_before_discovery(
    names: tuple[str, ...],
) -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(provider, (_candidate("same", "Same"),))
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=names,
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert discovery.calls == 0
    assert persistence.discovered_calls == 0


def test_missing_candidate_fails_entire_batch() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(provider, (_candidate("present", "Present"),))
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=("present", "missing"),
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert persistence.discovered_calls == 0


def test_embedding_candidate_without_dimension_fails_without_persistence() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    candidate = ModelCandidate(
        provider_model_name="embedding-model",
        display_name="Embedding model",
        model_type=ModelType.EMBEDDING,
        capabilities=frozenset(),
        embedding_dimension=None,
    )
    discovery = FakeDiscovery(provider, (candidate,))
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=("embedding-model",),
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert discovery.calls == 1
    assert persistence.discovered_calls == 0


def test_denied_registration_stops_before_discovery_and_persistence() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(provider, (_candidate("model", "Model"),))
    permission = DenyPermission()
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permission,  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=("model",),
            )
        )

    assert raised.value.code is ErrorCode.FORBIDDEN
    assert permission.permission == "model_providers.manage"
    assert discovery.calls == 0
    assert persistence.discovered_calls == 0


@pytest.mark.parametrize(
    "provider_type",
    [ProviderType.AZURE_OPENAI, ProviderType.OPENAI_COMPATIBLE],
)
def test_manual_only_provider_rejects_discovered_mode_without_discovery(
    provider_type: ProviderType,
) -> None:
    provider = _provider(provider_type)
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(provider, (_candidate("model", "Model"),))
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=("model",),
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert discovery.calls == 0
    assert persistence.discovered_calls == 0


def test_discovery_errors_are_preserved_without_registration_remapping() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)

    class FailingDiscovery:
        async def discover(self, **_kwargs: object) -> ProviderDiscoveryResult:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Model discovery is temporarily unavailable.",
                retryable=True,
            )

    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=FailingDiscovery(),  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=("model",),
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True


def test_persistence_conflict_is_registration_conflict() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    persistence.error = ModelProviderConflictError("stale detail")
    discovery = FakeDiscovery(provider, (_candidate("model", "Model"),))
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_discovered(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_names=("model",),
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert "stale detail" not in raised.value.message


def test_manual_registration_uses_declared_metadata_without_discovery() -> None:
    base = _provider()
    provider = ConfiguredProvider(
        organization_public_id=base.organization_public_id,
        provider_id=base.provider_id,
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        display_name=base.display_name,
        settings=OpenAICompatibleSettings(base_url="https://models.example.com"),
        enabled=True,
        credential_reference=base.credential_reference,
        validation_status=base.validation_status,
        last_validated_at=base.last_validated_at,
    )
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(provider, ())
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.register_manual(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=provider.provider_id.value,
            provider_model_name="operator-alias",
            display_name="Operator alias",
            model_type=ModelType.CHAT,
            capabilities=frozenset({ModelCapability.STREAMING}),
            embedding_dimension=None,
        )
    )

    assert discovery.calls == 0
    assert persistence.manual_calls == 1
    assert result[0].model.provider_model_name == "operator-alias"
    assert result[0].model.display_name == "Operator alias"
    assert result[0].model.enabled is True


@pytest.mark.parametrize(
    "provider_type",
    [ProviderType.OPENAI, ProviderType.ANTHROPIC, ProviderType.GEMINI],
)
def test_discovery_provider_rejects_manual_mode(provider_type: ProviderType) -> None:
    provider = _provider(provider_type)
    persistence = FakePersistence(provider)
    discovery = FakeDiscovery(provider, ())
    service = RegisterConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
        discovery=discovery,  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.register_manual(
                organization_public_id=provider.organization_public_id,
                user_public_id=uuid4(),
                provider_public_id=provider.provider_id.value,
                provider_model_name="model",
                display_name="Model",
                model_type=ModelType.CHAT,
                capabilities=frozenset({ModelCapability.STREAMING}),
                embedding_dimension=None,
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert discovery.calls == 0
    assert persistence.manual_calls == 0


def test_list_filters_are_collection_scoped_and_wrong_provider_is_empty() -> None:
    provider = _provider()
    persistence = FakePersistence(provider)
    persistence.models = (
        ConfiguredModel(
            organization_public_id=provider.organization_public_id,
            model_id=ConfiguredModelId(uuid4()),
            provider_id=provider.provider_id,
            provider_model_name="model",
            display_name="Model",
            model_type=ModelType.CHAT,
        ),
    )
    service = ListConfiguredModels(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=AllowPermission(),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.execute(
            organization_public_id=provider.organization_public_id,
            user_public_id=uuid4(),
            provider_public_id=uuid4(),
        )
    )

    assert result == ()
