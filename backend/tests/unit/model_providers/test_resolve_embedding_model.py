from __future__ import annotations

import asyncio
from copy import copy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from tests.unit.model_providers.test_resolve_chat_model import (
    FakeCredentialStore,
    FakePersistence,
)

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    ResolvedEmbeddingModel,
    ResolveEmbeddingModel,
)
from nexus.model_providers.domain import (
    AzureOpenAISettings,
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    ModelProviderConfigurationError,
    ModelType,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStore,
    CredentialStoreError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
)


def configuration(
    organization: int = 1, *, default: bool = False
) -> OrganizationModelProviderConfiguration:
    provider = ConfiguredProvider(
        organization_public_id=UUID(int=organization),
        provider_id=OrganizationProviderId(UUID(int=100 + organization)),
        provider_type=ProviderType.OPENAI
        if organization == 1
        else ProviderType.AZURE_OPENAI,
        display_name="Embedding provider",
        settings=OpenAISettings()
        if organization == 1
        else AzureOpenAISettings(
            endpoint="https://embedding.openai.azure.example", api_version="2026-09-01"
        ),
        enabled=True,
        credential_reference=CredentialReference(UUID(int=200 + organization)),
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    model = ConfiguredModel(
        organization_public_id=provider.organization_public_id,
        model_id=ConfiguredModelId(UUID(int=300 + organization)),
        provider_id=provider.provider_id,
        provider_model_name=f"embedding-deployment-{organization}",
        display_name="Embedding model",
        model_type=ModelType.EMBEDDING,
        embedding_dimension=1536 if organization == 1 else 3072,
    )
    return OrganizationModelProviderConfiguration(
        organization_public_id=provider.organization_public_id,
        providers=(provider,),
        models=(model,),
        defaults=DefaultModelSelection(embedding=model.model_id if default else None),
    )


def service_for(
    *configurations: OrganizationModelProviderConfiguration,
) -> tuple[ResolveEmbeddingModel, FakePersistence, FakeCredentialStore]:
    persistence = FakePersistence({c.organization_public_id: c for c in configurations})
    secrets = {}
    for config in configurations:
        provider = config.providers[0]
        assert provider.credential_reference is not None
        secrets[
            (
                config.organization_public_id,
                provider.provider_id,
                provider.credential_reference,
            )
        ] = ProviderCredentialSecret(
            f"private credential for tenant {config.organization_public_id.int}"
        )
    store = FakeCredentialStore(persistence, secrets)
    return (
        ResolveEmbeddingModel(
            cast(ModelProviderPersistence, persistence), cast(CredentialStore, store)
        ),
        persistence,
        store,
    )


def execute(
    service: ResolveEmbeddingModel,
    config: OrganizationModelProviderConfiguration,
    *,
    default: bool = False,
) -> ResolvedEmbeddingModel:
    return asyncio.run(
        service.execute(
            organization_public_id=config.organization_public_id,
            model_id=None if default else config.models[0].model_id,
        )
    )


@pytest.mark.parametrize("organization", [1, 2])
@pytest.mark.parametrize("use_default", [False, True])
def test_resolves_explicit_or_default_embedding_target(organization, use_default):
    config = configuration(organization, default=use_default)
    service, persistence, store = service_for(config)
    target = execute(service, config, default=use_default)
    model, provider = config.models[0], config.providers[0]
    assert target.model_id == model.model_id
    assert target.provider_id == provider.provider_id
    assert target.provider_type is provider.provider_type
    assert target.provider_model_name == model.provider_model_name
    assert target.embedding_dimension == model.embedding_dimension
    assert target.settings is provider.settings
    key = (
        config.organization_public_id,
        provider.provider_id,
        provider.credential_reference,
    )
    assert target.credential is store.secrets[key]
    assert persistence.calls == [("load", config.organization_public_id)]
    assert store.calls == [key]


def test_explicit_selection_overrides_the_embedding_default():
    config = configuration(default=True)
    explicit = replace(
        config.models[0],
        model_id=ConfiguredModelId(UUID(int=999)),
        embedding_dimension=768,
    )
    config = replace(config, models=(*config.models, explicit))
    service, _, _ = service_for(config)
    target = asyncio.run(
        service.execute(
            organization_public_id=config.organization_public_id,
            model_id=explicit.model_id,
        )
    )
    assert (target.model_id, target.embedding_dimension) == (explicit.model_id, 768)


@pytest.mark.parametrize("present", [False, True])
def test_missing_configuration_or_embedding_default_is_a_safe_conflict(present):
    config = configuration()
    service, persistence, store = service_for(config)
    if not present:
        persistence.configurations.clear()
    with pytest.raises(NexusError) as raised:
        execute(service, config, default=True)
    assert raised.value.code is ErrorCode.CONFLICT
    assert raised.value.message == "No embedding model is configured."
    assert store.calls == []


@pytest.mark.parametrize("present", [False, True])
def test_foreign_and_missing_explicit_ids_are_indistinguishable_without_credential_lookup(
    present,
):
    first, second = configuration(), configuration(2, default=True)
    service, persistence, store = service_for(first, second)
    if not present:
        persistence.configurations.pop(second.organization_public_id)
    errors = []
    for model_id in (first.models[0].model_id, ConfiguredModelId(UUID(int=999))):
        with pytest.raises(NexusError) as raised:
            asyncio.run(
                service.execute(
                    organization_public_id=second.organization_public_id,
                    model_id=model_id,
                )
            )
        errors.append((raised.value.code, raised.value.message))
    assert (
        errors == [(ErrorCode.NOT_FOUND, "The requested resource was not found.")] * 2
    )
    assert store.calls == []


@pytest.mark.parametrize("organization", [None, "invalid", 1, UUID(int=0)])
def test_invalid_tenant_is_rejected_before_any_io(organization):
    config = configuration()
    service, persistence, store = service_for(config)
    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization, model_id=config.models[0].model_id
            )
        )
    assert raised.value.code is ErrorCode.VALIDATION_ERROR
    assert persistence.calls == store.calls == []


@pytest.mark.parametrize(
    "model_id", [UUID(int=301), "model", ConfiguredModelId(UUID(int=0))]
)
def test_invalid_model_selection_is_rejected_before_any_io(model_id):
    config = configuration()
    service, persistence, store = service_for(config)
    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=config.organization_public_id, model_id=model_id
            )
        )
    assert raised.value.code is ErrorCode.VALIDATION_ERROR
    assert persistence.calls == store.calls == []


@pytest.mark.parametrize("model_type", [ModelType.CHAT, ModelType.RERANKER])
def test_other_model_types_are_rejected_before_credential_resolution(model_type):
    config = configuration()
    model = replace(config.models[0], model_type=model_type, embedding_dimension=None)
    config = replace(config, models=(model,))
    service, _, store = service_for(config)
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.CONFLICT
    assert store.calls == []


def test_disabled_embedding_model_is_rejected_before_credential_resolution():
    config = configuration()
    config = replace(config, models=(replace(config.models[0], enabled=False),))
    service, _, store = service_for(config)
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.CONFLICT
    assert store.calls == []


@pytest.mark.parametrize("dimension", [None, True, False, 1.0, "1536", 0, -1])
def test_invalid_dimension_snapshot_is_rejected_before_credential_resolution(dimension):
    config = configuration()
    malformed = copy(config.models[0])
    object.__setattr__(malformed, "embedding_dimension", dimension)
    service, _, store = service_for(config)
    object.__setattr__(config, "models", (malformed,))
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.CONFLICT
    assert store.calls == []


@pytest.mark.parametrize(
    "status",
    [
        ProviderValidationStatus.UNVALIDATED,
        ProviderValidationStatus.INVALID_CREDENTIALS,
        ProviderValidationStatus.UNREACHABLE,
        ProviderValidationStatus.UNSUPPORTED_CONFIGURATION,
    ],
)
def test_unvalidated_or_failed_provider_is_rejected_before_store_availability(status):
    config = configuration()
    provider = replace(
        config.providers[0],
        validation_status=status,
        last_validated_at=None
        if status is ProviderValidationStatus.UNVALIDATED
        else datetime(2026, 1, 1, tzinfo=UTC),
    )
    config = replace(config, providers=(provider,))
    persistence = FakePersistence({config.organization_public_id: config})
    service = ResolveEmbeddingModel(cast(ModelProviderPersistence, persistence), None)
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.CONFLICT


@pytest.mark.parametrize(
    "changes", [{"enabled": False}, {"credential_reference": None}]
)
def test_disabled_or_uncredentialed_provider_is_rejected_before_lookup(changes):
    config = configuration()
    service, _, store = service_for(config)
    object.__setattr__(config, "providers", (replace(config.providers[0], **changes),))
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.CONFLICT
    assert store.calls == []


@pytest.mark.parametrize(
    "broken", ["configuration", "model", "provider", "relationship", "default", "type"]
)
def test_malformed_or_cross_tenant_snapshots_fail_closed_before_credential_access(
    broken,
):
    config = configuration()
    service, persistence, store = service_for(config)
    if broken == "type":
        persistence.configurations[config.organization_public_id] = object()
    elif broken == "configuration":
        persistence.configurations[config.organization_public_id] = configuration(2)
    elif broken in {"model", "provider"}:
        item = copy(config.models[0] if broken == "model" else config.providers[0])
        object.__setattr__(item, "organization_public_id", UUID(int=2))
        object.__setattr__(
            config, "models" if broken == "model" else "providers", (item,)
        )
    elif broken == "relationship":
        object.__setattr__(config, "providers", ())
    else:
        object.__setattr__(
            config,
            "defaults",
            DefaultModelSelection(embedding=ConfiguredModelId(UUID(int=999))),
        )
    with pytest.raises(NexusError) as raised:
        execute(service, config, default=broken == "default")
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True
    assert store.calls == []


@pytest.mark.parametrize(
    "error",
    [
        ModelProviderPersistenceError("unsafe persistence detail"),
        ModelProviderConfigurationError("unsafe configuration detail"),
    ],
)
def test_configuration_failures_use_safe_existing_error_conventions(error):
    config = configuration()
    service, persistence, store = service_for(config)
    persistence.error = error
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True
    assert "unsafe" not in str(raised.value)
    assert store.calls == []


def test_eligible_target_requires_an_available_credential_store():
    config = configuration()
    service, _, _ = service_for(config)
    with pytest.raises(NexusError) as raised:
        execute(replace(service, credential_store=None), config)
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    "error,code,retryable",
    [
        (
            CredentialNotFoundError("unsafe credential detail"),
            ErrorCode.CONFLICT,
            False,
        ),
        (
            CredentialStoreError("unsafe credential detail"),
            ErrorCode.SERVICE_UNAVAILABLE,
            True,
        ),
        (
            ModelProviderConfigurationError("unsafe credential detail"),
            ErrorCode.SERVICE_UNAVAILABLE,
            True,
        ),
    ],
)
def test_credential_failures_are_normalized_without_sensitive_details(
    error, code, retryable
):
    config = configuration()
    service, _, store = service_for(config)
    store.error = error
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is code
    assert raised.value.retryable is retryable
    assert "unsafe" not in str(raised.value)


def test_unprotected_credential_from_broken_store_is_rejected(monkeypatch):
    config = configuration()
    service, _, store = service_for(config)
    monkeypatch.setattr(store, "resolve", AsyncMock(return_value="private raw secret"))
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert "private raw secret" not in str(raised.value)


@pytest.mark.parametrize("boundary", ["configuration", "credential"])
def test_cancellation_propagates_from_each_io_boundary(monkeypatch, boundary):
    config = configuration()
    service, persistence, store = service_for(config)
    cancelled = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(
        persistence if boundary == "configuration" else store,
        "load_configuration" if boundary == "configuration" else "resolve",
        cancelled,
    )
    with pytest.raises(asyncio.CancelledError):
        execute(service, config)
    if boundary == "configuration":
        assert store.calls == []


def test_concurrent_organizations_resolve_distinct_models_dimensions_and_credentials():
    first, second = configuration(default=True), configuration(2, default=True)
    service, _, store = service_for(first, second)

    async def resolve_both():
        return await asyncio.gather(
            *(
                service.execute(
                    organization_public_id=c.organization_public_id, model_id=None
                )
                for c in (first, second)
            )
        )

    targets = asyncio.run(resolve_both())
    assert targets[0].model_id != targets[1].model_id
    assert [t.embedding_dimension for t in targets] == [1536, 3072]
    for config, target in zip((first, second), targets):
        provider = config.providers[0]
        key = (
            config.organization_public_id,
            provider.provider_id,
            provider.credential_reference,
        )
        assert target.credential is store.secrets[key]
        assert target.provider_id == provider.provider_id
    assert set(store.calls) == set(store.secrets)


def test_resolution_reloads_the_current_default_instead_of_caching_a_target():
    config = configuration(default=True)
    service, persistence, _ = service_for(config)
    first = execute(service, config, default=True)
    next_model = replace(
        config.models[0],
        model_id=ConfiguredModelId(UUID(int=999)),
        embedding_dimension=768,
    )
    persistence.configurations[config.organization_public_id] = replace(
        config,
        models=(*config.models, next_model),
        defaults=DefaultModelSelection(embedding=next_model.model_id),
    )
    second = execute(service, config, default=True)
    assert first.model_id != second.model_id
    assert second.embedding_dimension == 768
    assert len(persistence.calls) == 2


def test_resolved_target_is_frozen_and_credential_is_redacted():
    config = configuration()
    service, _, _ = service_for(config)
    target = execute(service, config)
    assert "private credential" not in repr(target)
    assert "private credential" not in str(target)
    assert "private credential" not in repr(target.credential)
    assert "private credential" not in str(target.credential)
    with pytest.raises(FrozenInstanceError):
        target.embedding_dimension = 1


@pytest.mark.parametrize("dimension", [None, True, 1.0, "1536", 0, -1])
def test_resolved_target_requires_positive_exact_dimension(dimension):
    service, _, _ = service_for(config := configuration())
    with pytest.raises(ModelProviderConfigurationError):
        replace(execute(service, config), embedding_dimension=dimension)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_id", UUID(int=1)),
        ("model_id", ConfiguredModelId(UUID(int=0))),
        ("provider_id", UUID(int=1)),
        ("provider_id", OrganizationProviderId(UUID(int=0))),
        ("provider_type", "openai"),
        ("provider_model_name", " "),
        ("provider_model_name", "x" * 257),
        ("credential", "private raw secret"),
    ],
)
def test_resolved_target_rejects_invalid_runtime_values(field, value):
    service, _, _ = service_for(config := configuration())
    with pytest.raises(ModelProviderConfigurationError):
        replace(execute(service, config), **{field: value})


def test_malformed_target_snapshot_uses_safe_service_error():
    config = configuration()
    service, _, _ = service_for(config)
    object.__setattr__(config.models[0], "provider_model_name", " ")
    with pytest.raises(NexusError) as raised:
        execute(service, config)
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
