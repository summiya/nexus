"""Organization-scoped runtime chat-model resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application._shared import (
    conflict,
    credential_unavailable,
    load_configuration,
    unavailable,
)
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStore,
    CredentialStoreError,
    ModelProviderPersistence,
)

_NOT_FOUND = "The requested resource was not found."
_NO_DEFAULT = "No chat model is configured."


@dataclass(frozen=True, slots=True)
class ResolvedChatModel:
    """One immutable provider-neutral runtime target and its redacted credential."""

    model_id: ConfiguredModelId
    provider_id: OrganizationProviderId
    provider_type: ProviderType
    provider_model_name: str
    settings: ProviderSettings
    credential: ProviderCredentialSecret = field(repr=False)


@dataclass(frozen=True)
class ResolveChatModel:
    """Resolve one eligible tenant-owned chat model for a later invocation."""

    persistence: ModelProviderPersistence
    credential_store: CredentialStore | None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        model_id: ConfiguredModelId | None,
    ) -> ResolvedChatModel:
        try:
            configuration = await load_configuration(
                self.persistence,
                organization_public_id=organization_public_id,
            )
        except ModelProviderConfigurationError as exc:
            raise unavailable() from exc

        selected_model = _resolve_model(configuration, model_id=model_id)
        _require_model_eligible(selected_model)
        provider = _resolve_provider(configuration, selected_model.provider_id)
        _require_provider_eligible(provider)

        credential_reference = provider.credential_reference
        if credential_reference is None:
            raise conflict()

        store = self.credential_store
        if store is None:
            raise credential_unavailable()
        try:
            credential = await store.resolve(
                organization_public_id=organization_public_id,
                provider_id=provider.provider_id,
                credential_reference=credential_reference,
            )
        except CredentialNotFoundError as exc:
            raise conflict() from exc
        except CredentialStoreError as exc:
            raise credential_unavailable() from exc

        return ResolvedChatModel(
            model_id=selected_model.model_id,
            provider_id=provider.provider_id,
            provider_type=provider.provider_type,
            provider_model_name=selected_model.provider_model_name,
            settings=provider.settings,
            credential=credential,
        )


def _resolve_model(
    configuration: OrganizationModelProviderConfiguration | None,
    *,
    model_id: ConfiguredModelId | None,
) -> ConfiguredModel:
    if configuration is None:
        if model_id is not None:
            raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND)
        raise NexusError(ErrorCode.CONFLICT, _NO_DEFAULT)

    selected_id = model_id if model_id is not None else configuration.defaults.chat
    if selected_id is None:
        raise NexusError(ErrorCode.CONFLICT, _NO_DEFAULT)

    for model in configuration.models:
        if model.model_id == selected_id:
            return model

    if model_id is not None:
        raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND)
    raise unavailable()


def _require_model_eligible(model: ConfiguredModel) -> None:
    if (
        not model.enabled
        or model.model_type is not ModelType.CHAT
        or ModelCapability.STREAMING not in model.capabilities
    ):
        raise conflict()


def _resolve_provider(
    configuration: OrganizationModelProviderConfiguration | None,
    provider_id: OrganizationProviderId,
) -> ConfiguredProvider:
    if configuration is None:  # pragma: no cover - model resolution proved otherwise
        raise unavailable()
    for provider in configuration.providers:
        if provider.provider_id == provider_id:
            return provider
    raise unavailable()


def _require_provider_eligible(provider: ConfiguredProvider) -> None:
    if (
        not provider.enabled
        or provider.validation_status is not ProviderValidationStatus.VALID
    ):
        raise conflict()


__all__ = ["ResolveChatModel", "ResolvedChatModel"]
