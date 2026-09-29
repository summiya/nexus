from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import ResolveChatModel, ResolvedChatModel
from nexus.model_providers.domain import (
    AzureOpenAISettings,
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
    ProviderCredentialSecret,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStoreError,
    ModelProviderPersistenceError,
)

type CredentialKey = tuple[UUID, OrganizationProviderId, CredentialReference]


class FakePersistence:
    def __init__(
        self,
        configurations: dict[UUID, OrganizationModelProviderConfiguration],
    ) -> None:
        self.configurations = configurations
        self.calls: list[tuple[str, UUID]] = []
        self.error: Exception | None = None
        self.read_in_progress = False

    async def load_configuration(
        self,
        *,
        organization_public_id: UUID,
    ) -> OrganizationModelProviderConfiguration | None:
        self.calls.append(("load", organization_public_id))
        self.read_in_progress = True
        try:
            await asyncio.sleep(0)
            if self.error is not None:
                raise self.error
            return self.configurations.get(organization_public_id)
        finally:
            self.read_in_progress = False


class FakeCredentialStore:
    def __init__(
        self,
        persistence: FakePersistence,
        secrets: dict[CredentialKey, ProviderCredentialSecret] | None = None,
    ) -> None:
        self.persistence = persistence
        self.secrets = {} if secrets is None else secrets
        self.calls: list[CredentialKey] = []
        self.error: Exception | None = None

    async def resolve(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> ProviderCredentialSecret:
        assert not self.persistence.read_in_progress
        key = (organization_public_id, provider_id, credential_reference)
        self.calls.append(key)
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        try:
            return self.secrets[key]
        except KeyError:
            raise CredentialNotFoundError("unsafe missing detail") from None


def _provider(
    organization_id: UUID,
    *,
    provider_type: ProviderType = ProviderType.OPENAI,
) -> ConfiguredProvider:
    settings = (
        AzureOpenAISettings(
            endpoint="https://runtime.openai.azure.example",
            api_version="2026-09-01",
        )
        if provider_type is ProviderType.AZURE_OPENAI
        else OpenAISettings()
    )
    return ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=provider_type,
        display_name="Runtime provider",
        settings=settings,
        enabled=True,
        credential_reference=CredentialReference(uuid4()),
        validation_status=ProviderValidationStatus.VALID,
        last_validated_at=datetime.now(UTC),
    )


def _model(
    organization_id: UUID,
    provider_id: OrganizationProviderId,
    *,
    model_type: ModelType = ModelType.CHAT,
    capabilities: frozenset[ModelCapability] = frozenset({ModelCapability.STREAMING}),
) -> ConfiguredModel:
    return ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider_id,
        provider_model_name="provider-runtime-model",
        display_name="Runtime model",
        model_type=model_type,
        capabilities=capabilities if model_type is ModelType.CHAT else frozenset(),
        embedding_dimension=1536 if model_type is ModelType.EMBEDDING else None,
    )


def _configuration(
    organization_id: UUID,
    provider: ConfiguredProvider,
    model: ConfiguredModel,
    *,
    default: bool = False,
) -> OrganizationModelProviderConfiguration:
    return OrganizationModelProviderConfiguration(
        organization_public_id=organization_id,
        providers=(provider,),
        models=(model,),
        defaults=DefaultModelSelection(chat=model.model_id if default else None),
    )


def _service(
    configuration: OrganizationModelProviderConfiguration,
    secret: ProviderCredentialSecret | None = None,
) -> tuple[ResolveChatModel, FakePersistence, FakeCredentialStore]:
    persistence = FakePersistence({configuration.organization_public_id: configuration})
    provider = configuration.providers[0]
    assert provider.credential_reference is not None
    store = FakeCredentialStore(
        persistence,
        {
            (
                configuration.organization_public_id,
                provider.provider_id,
                provider.credential_reference,
            ): secret or ProviderCredentialSecret("runtime-secret"),
        },
    )
    return (
        ResolveChatModel(  # type: ignore[arg-type]
            persistence=persistence,
            credential_store=store,  # type: ignore[arg-type]
        ),
        persistence,
        store,
    )


@pytest.mark.parametrize("use_default", [False, True])
def test_resolves_explicit_or_default_chat_model(use_default: bool) -> None:
    organization_id = uuid4()
    provider = _provider(organization_id, provider_type=ProviderType.AZURE_OPENAI)
    model = _model(organization_id, provider.provider_id)
    configuration = _configuration(
        organization_id,
        provider,
        model,
        default=use_default,
    )
    service, persistence, store = _service(configuration)

    result = asyncio.run(
        service.execute(
            organization_public_id=organization_id,
            model_id=None if use_default else model.model_id,
        )
    )

    assert result == ResolvedChatModel(
        model_id=model.model_id,
        provider_id=provider.provider_id,
        provider_type=provider.provider_type,
        provider_model_name=model.provider_model_name,
        settings=provider.settings,
        credential=store.secrets[
            (organization_id, provider.provider_id, provider.credential_reference)
        ],
    )
    assert persistence.calls == [("load", organization_id)]
    assert store.calls == [
        (organization_id, provider.provider_id, provider.credential_reference)
    ]


def test_no_chat_default_is_a_safe_conflict() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id)
    service, _, store = _service(_configuration(organization_id, provider, model))

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(organization_public_id=organization_id, model_id=None)
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert raised.value.message == "No chat model is configured."
    assert store.calls == []


def test_unknown_and_wrong_tenant_models_are_indistinguishable_without_store() -> None:
    first_organization_id = uuid4()
    second_organization_id = uuid4()
    first_provider = _provider(first_organization_id)
    first_model = _model(first_organization_id, first_provider.provider_id)
    second_provider = _provider(second_organization_id)
    second_model = _model(second_organization_id, second_provider.provider_id)
    persistence = FakePersistence(
        {
            first_organization_id: _configuration(
                first_organization_id, first_provider, first_model
            ),
            second_organization_id: _configuration(
                second_organization_id, second_provider, second_model
            ),
        }
    )
    service = ResolveChatModel(  # type: ignore[arg-type]
        persistence=persistence,
        credential_store=None,
    )

    messages = []
    for model_id in (first_model.model_id, ConfiguredModelId(uuid4())):
        with pytest.raises(NexusError) as raised:
            asyncio.run(
                service.execute(
                    organization_public_id=second_organization_id,
                    model_id=model_id,
                )
            )
        assert raised.value.code is ErrorCode.NOT_FOUND
        messages.append(raised.value.message)

    assert messages == [
        "The requested resource was not found.",
        "The requested resource was not found.",
    ]


@pytest.mark.parametrize(
    "replacement",
    [
        {"enabled": False},
        {"capabilities": frozenset()},
    ],
)
def test_ineligible_chat_model_is_rejected_before_credential_resolution(
    replacement: dict[str, object],
) -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = replace(_model(organization_id, provider.provider_id), **replacement)
    service, _, store = _service(_configuration(organization_id, provider, model))

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=model.model_id,
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert store.calls == []


@pytest.mark.parametrize("model_type", [ModelType.EMBEDDING, ModelType.RERANKER])
def test_non_chat_model_is_rejected_before_credential_resolution(
    model_type: ModelType,
) -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id, model_type=model_type)
    service, _, store = _service(_configuration(organization_id, provider, model))

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=model.model_id,
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert store.calls == []


@pytest.mark.parametrize(
    "provider",
    [
        {"enabled": False},
        {
            "validation_status": ProviderValidationStatus.UNVALIDATED,
            "last_validated_at": None,
        },
        {"validation_status": ProviderValidationStatus.INVALID_CREDENTIALS},
        {"validation_status": ProviderValidationStatus.UNREACHABLE},
        {"validation_status": ProviderValidationStatus.UNSUPPORTED_CONFIGURATION},
        {"credential_reference": None},
    ],
)
def test_ineligible_provider_is_rejected_before_store_availability_is_checked(
    provider: dict[str, object],
) -> None:
    organization_id = uuid4()
    configured_provider = replace(_provider(organization_id), **provider)
    model = _model(organization_id, configured_provider.provider_id)
    configuration = _configuration(organization_id, configured_provider, model)
    persistence = FakePersistence({organization_id: configuration})
    service = ResolveChatModel(  # type: ignore[arg-type]
        persistence=persistence,
        credential_store=None,
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=model.model_id,
            )
        )

    assert raised.value.code is ErrorCode.CONFLICT


def test_missing_provider_relationship_is_safe_service_unavailable() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id)
    malformed = object.__new__(OrganizationModelProviderConfiguration)
    object.__setattr__(malformed, "organization_public_id", organization_id)
    object.__setattr__(malformed, "providers", ())
    object.__setattr__(malformed, "models", (model,))
    object.__setattr__(malformed, "defaults", DefaultModelSelection())
    persistence = FakePersistence({organization_id: malformed})
    service = ResolveChatModel(  # type: ignore[arg-type]
        persistence=persistence,
        credential_store=None,
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=model.model_id,
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True


def test_eligible_target_requires_a_configured_credential_store() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id)
    persistence = FakePersistence(
        {organization_id: _configuration(organization_id, provider, model)}
    )
    service = ResolveChatModel(  # type: ignore[arg-type]
        persistence=persistence,
        credential_store=None,
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=model.model_id,
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("error", "expected_code", "retryable"),
    [
        (CredentialNotFoundError("unsafe detail"), ErrorCode.CONFLICT, False),
        (
            CredentialStoreError("unsafe detail"),
            ErrorCode.SERVICE_UNAVAILABLE,
            True,
        ),
    ],
)
def test_credential_failures_are_normalized_without_error_details(
    error: Exception,
    expected_code: ErrorCode,
    retryable: bool,
) -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id)
    service, _, store = _service(_configuration(organization_id, provider, model))
    store.error = error

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=model.model_id,
            )
        )

    assert raised.value.code is expected_code
    assert raised.value.retryable is retryable
    assert "unsafe detail" not in raised.value.message


@pytest.mark.parametrize(
    "error",
    [
        ModelProviderPersistenceError("unsafe persistence detail"),
        ModelProviderConfigurationError("unsafe configuration detail"),
    ],
)
def test_configuration_load_failures_are_safe_service_unavailable(
    error: Exception,
) -> None:
    organization_id = uuid4()
    persistence = FakePersistence({})
    persistence.error = error
    service = ResolveChatModel(  # type: ignore[arg-type]
        persistence=persistence,
        credential_store=None,
    )

    with pytest.raises(NexusError) as raised:
        asyncio.run(
            service.execute(
                organization_public_id=organization_id,
                model_id=None,
            )
        )

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True
    assert "unsafe" not in raised.value.message


def test_persistence_read_completes_before_credential_resolution() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id)
    service, persistence, store = _service(
        _configuration(organization_id, provider, model)
    )

    asyncio.run(
        service.execute(
            organization_public_id=organization_id,
            model_id=model.model_id,
        )
    )

    assert persistence.calls == [("load", organization_id)]
    assert store.calls == [
        (organization_id, provider.provider_id, provider.credential_reference)
    ]


def test_concurrent_organizations_resolve_isolated_runtime_targets() -> None:
    first_organization_id = uuid4()
    second_organization_id = uuid4()
    first_provider = _provider(first_organization_id)
    second_provider = _provider(
        second_organization_id,
        provider_type=ProviderType.AZURE_OPENAI,
    )
    first_model = _model(first_organization_id, first_provider.provider_id)
    second_model = _model(second_organization_id, second_provider.provider_id)
    persistence = FakePersistence(
        {
            first_organization_id: _configuration(
                first_organization_id, first_provider, first_model
            ),
            second_organization_id: _configuration(
                second_organization_id, second_provider, second_model
            ),
        }
    )
    assert first_provider.credential_reference is not None
    assert second_provider.credential_reference is not None
    first_secret = ProviderCredentialSecret("organization-a-secret")
    second_secret = ProviderCredentialSecret("organization-b-secret")
    store = FakeCredentialStore(
        persistence,
        {
            (
                first_organization_id,
                first_provider.provider_id,
                first_provider.credential_reference,
            ): first_secret,
            (
                second_organization_id,
                second_provider.provider_id,
                second_provider.credential_reference,
            ): second_secret,
        },
    )
    service = ResolveChatModel(  # type: ignore[arg-type]
        persistence=persistence,
        credential_store=store,  # type: ignore[arg-type]
    )

    async def resolve_both() -> tuple[ResolvedChatModel, ResolvedChatModel]:
        first, second = await asyncio.gather(
            service.execute(
                organization_public_id=first_organization_id,
                model_id=first_model.model_id,
            ),
            service.execute(
                organization_public_id=second_organization_id,
                model_id=second_model.model_id,
            ),
        )
        return first, second

    first, second = asyncio.run(resolve_both())

    assert first.credential is first_secret
    assert first.provider_id == first_provider.provider_id
    assert first.provider_type is ProviderType.OPENAI
    assert second.credential is second_secret
    assert second.provider_id == second_provider.provider_id
    assert second.provider_type is ProviderType.AZURE_OPENAI
    assert set(store.calls) == set(store.secrets)


def test_runtime_target_never_represents_credential_plaintext() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id)
    model = _model(organization_id, provider.provider_id)
    plaintext = "credential-plaintext-must-not-leak"
    service, _, _ = _service(
        _configuration(organization_id, provider, model),
        ProviderCredentialSecret(plaintext),
    )

    result = asyncio.run(
        service.execute(
            organization_public_id=organization_id,
            model_id=model.model_id,
        )
    )

    assert plaintext not in repr(result)
    assert plaintext not in str(result)
    with pytest.raises((AttributeError, TypeError)):
        result.provider_model_name = "changed"  # type: ignore[misc]
