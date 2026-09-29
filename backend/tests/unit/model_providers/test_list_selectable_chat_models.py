from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application import (
    ListSelectableChatModels,
    SelectableChatModel,
    SelectableChatModels,
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
from nexus.model_providers.ports import ModelProviderPersistenceError


class FakePersistence:
    def __init__(
        self,
        configurations: dict[UUID, OrganizationModelProviderConfiguration],
    ) -> None:
        self.configurations = configurations
        self.calls: list[UUID] = []
        self.error: Exception | None = None

    async def load_configuration(
        self, *, organization_public_id: UUID
    ) -> OrganizationModelProviderConfiguration | None:
        self.calls.append(organization_public_id)
        if self.error is not None:
            raise self.error
        return self.configurations.get(organization_public_id)


def _provider(
    organization_id: UUID,
    *,
    provider_type: ProviderType = ProviderType.OPENAI,
    enabled: bool = True,
    status: ProviderValidationStatus = ProviderValidationStatus.VALID,
    credential: bool = True,
    display_name: str = "OpenAI",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        organization_public_id=organization_id,
        provider_id=OrganizationProviderId(uuid4()),
        provider_type=provider_type,
        display_name=display_name,
        settings=OpenAISettings(),
        enabled=enabled,
        credential_reference=CredentialReference(uuid4()) if credential else None,
        validation_status=status,
        last_validated_at=(
            None
            if status is ProviderValidationStatus.UNVALIDATED
            else datetime.now(UTC)
        ),
    )


def _model(
    organization_id: UUID,
    provider_id: OrganizationProviderId,
    *,
    display_name: str = "GPT-5",
    model_type: ModelType = ModelType.CHAT,
    enabled: bool = True,
    streaming: bool = True,
) -> ConfiguredModel:
    return ConfiguredModel(
        organization_public_id=organization_id,
        model_id=ConfiguredModelId(uuid4()),
        provider_id=provider_id,
        provider_model_name=display_name.lower(),
        display_name=display_name,
        model_type=model_type,
        capabilities=(
            frozenset({ModelCapability.STREAMING})
            if model_type is ModelType.CHAT and streaming
            else frozenset()
        ),
        embedding_dimension=1536 if model_type is ModelType.EMBEDDING else None,
        enabled=enabled,
    )


def _configuration(
    organization_id: UUID,
    providers: tuple[ConfiguredProvider, ...],
    models: tuple[ConfiguredModel, ...],
    *,
    default: ConfiguredModelId | None = None,
) -> OrganizationModelProviderConfiguration:
    return OrganizationModelProviderConfiguration(
        organization_public_id=organization_id,
        providers=providers,
        models=models,
        defaults=DefaultModelSelection(chat=default),
    )


def _execute(
    persistence: FakePersistence, organization_id: UUID
) -> SelectableChatModels:
    return asyncio.run(
        ListSelectableChatModels(persistence=persistence).execute(  # type: ignore[arg-type]
            organization_public_id=organization_id
        )
    )


def test_lists_only_safe_metadata_and_eligible_default_in_source_order() -> None:
    organization_id = uuid4()
    first_provider = _provider(organization_id)
    second_provider = _provider(
        organization_id,
        provider_type=ProviderType.OPENAI,
        display_name="Second provider",
    )
    first_model = _model(organization_id, first_provider.provider_id)
    second_model = _model(
        organization_id,
        second_provider.provider_id,
        display_name="Second model",
    )
    configuration = _configuration(
        organization_id,
        (first_provider, second_provider),
        (first_model, second_model),
        default=second_model.model_id,
    )
    persistence = FakePersistence({organization_id: configuration})

    result = _execute(persistence, organization_id)

    assert result == SelectableChatModels(
        items=(
            SelectableChatModel(
                model_id=first_model.model_id,
                display_name=first_model.display_name,
                provider_type=first_provider.provider_type,
                provider_display_name=first_provider.display_name,
            ),
            SelectableChatModel(
                model_id=second_model.model_id,
                display_name=second_model.display_name,
                provider_type=second_provider.provider_type,
                provider_display_name=second_provider.display_name,
            ),
        ),
        default_model_id=second_model.model_id,
    )
    assert persistence.calls == [organization_id]
    assert "credential" not in SelectableChatModel.__dataclass_fields__


@pytest.mark.parametrize(
    ("provider_overrides", "model_overrides"),
    [
        ({}, {"enabled": False}),
        ({}, {"model_type": ModelType.EMBEDDING}),
        ({}, {"streaming": False}),
        ({"enabled": False}, {}),
        ({"status": ProviderValidationStatus.UNVALIDATED}, {}),
        ({"status": ProviderValidationStatus.INVALID_CREDENTIALS}, {}),
        ({"status": ProviderValidationStatus.UNREACHABLE}, {}),
        ({"status": ProviderValidationStatus.UNSUPPORTED_CONFIGURATION}, {}),
        ({"credential": False}, {}),
    ],
)
def test_excludes_ineligible_models(
    provider_overrides: dict[str, object], model_overrides: dict[str, object]
) -> None:
    organization_id = uuid4()
    provider = _provider(organization_id, **provider_overrides)  # type: ignore[arg-type]
    model = _model(
        organization_id,
        provider.provider_id,
        **model_overrides,  # type: ignore[arg-type]
    )
    persistence = FakePersistence(
        {organization_id: _configuration(organization_id, (provider,), (model,))}
    )

    assert _execute(persistence, organization_id) == SelectableChatModels(
        items=(), default_model_id=None
    )


def test_ineligible_default_is_null_while_other_model_remains_selectable() -> None:
    organization_id = uuid4()
    eligible_provider = _provider(organization_id)
    invalid_provider = _provider(
        organization_id,
        status=ProviderValidationStatus.INVALID_CREDENTIALS,
    )
    eligible_model = _model(organization_id, eligible_provider.provider_id)
    default_model = _model(organization_id, invalid_provider.provider_id)
    persistence = FakePersistence(
        {
            organization_id: _configuration(
                organization_id,
                (eligible_provider, invalid_provider),
                (eligible_model, default_model),
                default=default_model.model_id,
            )
        }
    )

    result = _execute(persistence, organization_id)

    assert tuple(item.model_id for item in result.items) == (eligible_model.model_id,)
    assert result.default_model_id is None


def test_empty_and_wrong_organization_configurations_are_isolated() -> None:
    first_organization_id = uuid4()
    second_organization_id = uuid4()
    provider = _provider(first_organization_id)
    model = _model(first_organization_id, provider.provider_id)
    persistence = FakePersistence(
        {
            first_organization_id: _configuration(
                first_organization_id, (provider,), (model,)
            )
        }
    )

    result = _execute(persistence, second_organization_id)

    assert result == SelectableChatModels(items=(), default_model_id=None)
    assert persistence.calls == [second_organization_id]


@pytest.mark.parametrize(
    "error",
    [
        ModelProviderPersistenceError("unsafe database detail"),
        ModelProviderConfigurationError("unsafe malformed state"),
    ],
)
def test_configuration_failures_are_safe_and_retryable(error: Exception) -> None:
    organization_id = uuid4()
    persistence = FakePersistence({})
    persistence.error = error

    with pytest.raises(NexusError) as raised:
        _execute(persistence, organization_id)

    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert raised.value.retryable is True
    assert "unsafe" not in raised.value.message
