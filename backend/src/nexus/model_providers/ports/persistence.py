"""Application-facing model-provider configuration persistence boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ConfiguredProvider,
    CredentialReference,
    DefaultModelSelection,
    ModelType,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
)


class ModelProviderPersistenceError(Exception):
    """An unexpected model-provider persistence failure occurred."""


class ModelProviderConflictError(Exception):
    """A provider or model uniqueness constraint conflicts."""


class ModelProviderReferenceError(Exception):
    """A required organization, provider, or model reference is missing."""


class ModelProviderDeleteRestrictedError(Exception):
    """A provider or model is still referenced and cannot be deleted."""


@dataclass(frozen=True)
class ProviderUpdateResult:
    """Authoritative provider update and any credential detached by a URL change."""

    provider: ConfiguredProvider
    cleared_credential_reference: CredentialReference | None = None


@dataclass(frozen=True)
class ConfiguredModelUpdateResult:
    model: ConfiguredModel
    provider_type: ProviderType


class ModelProviderPersistence(Protocol):
    """Tenant-scoped storage for one validated organization configuration."""

    async def load_configuration(
        self,
        *,
        organization_public_id: UUID,
    ) -> OrganizationModelProviderConfiguration | None: ...

    async def create_provider(self, provider: ConfiguredProvider) -> None: ...

    async def update_provider_configuration(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        display_name: str | None,
        settings: ProviderSettings | None,
    ) -> ProviderUpdateResult: ...

    async def set_provider_enabled(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        enabled: bool,
    ) -> ConfiguredProvider: ...

    async def set_provider_credential_reference(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        expected_credential_reference: CredentialReference | None,
        credential_reference: CredentialReference | None,
    ) -> ConfiguredProvider: ...

    async def record_provider_validation(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        expected_settings: ProviderSettings,
        expected_credential_reference: CredentialReference | None,
        status: ProviderValidationStatus,
    ) -> ConfiguredProvider: ...

    async def delete_provider(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> ConfiguredProvider: ...

    async def create_model(self, model: ConfiguredModel) -> None: ...

    async def create_discovered_models(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        expected_settings: ProviderSettings,
        expected_credential_reference: CredentialReference,
        models: tuple[ConfiguredModel, ...],
    ) -> None: ...

    async def create_manual_model(
        self,
        *,
        organization_public_id: UUID,
        model: ConfiguredModel,
    ) -> None: ...

    async def update_model(self, model: ConfiguredModel) -> None: ...

    async def set_model_enabled(
        self,
        *,
        organization_public_id: UUID,
        model_id: ConfiguredModelId,
        enabled: bool,
    ) -> ConfiguredModelUpdateResult: ...

    async def delete_model(
        self,
        *,
        organization_public_id: UUID,
        model_id: ConfiguredModelId,
    ) -> None: ...

    async def set_default(
        self,
        *,
        organization_public_id: UUID,
        model_type: ModelType,
        model_id: ConfiguredModelId | None,
    ) -> DefaultModelSelection: ...


__all__ = [
    "ConfiguredModelUpdateResult",
    "ModelProviderConflictError",
    "ModelProviderDeleteRestrictedError",
    "ModelProviderPersistence",
    "ModelProviderPersistenceError",
    "ModelProviderReferenceError",
    "ProviderUpdateResult",
]
