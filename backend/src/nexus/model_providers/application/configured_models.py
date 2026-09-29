"""Configured-model administration application services."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application._provider_model_discovery import (
    ProviderModelDiscovery,
)
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    NOT_FOUND,
    READ_PERMISSION,
    authorize,
    conflict,
    get_provider,
    load_configuration,
    unavailable,
)
from nexus.model_providers.domain import (
    ConfiguredModel,
    ConfiguredModelId,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
    OrganizationProviderId,
    ProviderType,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)

_DISCOVERED_PROVIDER_TYPES = frozenset(
    {ProviderType.OPENAI, ProviderType.ANTHROPIC, ProviderType.GEMINI}
)
_MAX_DISCOVERED_MODELS = 50


@dataclass(frozen=True)
class ConfiguredModelItem:
    model: ConfiguredModel
    provider_type: ProviderType


@dataclass(frozen=True)
class ListConfiguredModels:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID | None = None,
        model_type: ModelType | None = None,
        capability: ModelCapability | None = None,
        enabled: bool | None = None,
    ) -> tuple[ConfiguredModelItem, ...]:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=READ_PERMISSION,
        )
        configuration = await load_configuration(
            self.persistence,
            organization_public_id=organization_public_id,
        )
        if configuration is None:
            return ()
        provider_id = (
            OrganizationProviderId(provider_public_id)
            if provider_public_id is not None
            else None
        )
        provider_types = {
            provider.provider_id: provider.provider_type
            for provider in configuration.providers
        }
        return tuple(
            ConfiguredModelItem(
                model=model, provider_type=provider_types[model.provider_id]
            )
            for model in configuration.models
            if (provider_id is None or model.provider_id == provider_id)
            and (model_type is None or model.model_type is model_type)
            and (capability is None or capability in model.capabilities)
            and (enabled is None or model.enabled is enabled)
        )


@dataclass(frozen=True)
class RegisterConfiguredModels:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    discovery: ProviderModelDiscovery

    async def register_discovered(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        provider_model_names: tuple[str, ...],
    ) -> tuple[ConfiguredModelItem, ...]:
        await self._authorize(organization_public_id, user_public_id)
        if not 1 <= len(provider_model_names) <= _MAX_DISCOVERED_MODELS or len(
            set(provider_model_names)
        ) != len(provider_model_names):
            raise conflict()
        provider_id = OrganizationProviderId(provider_public_id)
        provider = await get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        if provider.provider_type not in _DISCOVERED_PROVIDER_TYPES:
            raise conflict()
        result = await self.discovery.discover(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        candidates = {
            candidate.provider_model_name: candidate for candidate in result.candidates
        }
        selected = []
        for name in provider_model_names:
            candidate = candidates.get(name)
            if candidate is None or (
                candidate.model_type is ModelType.EMBEDDING
                and candidate.embedding_dimension is None
            ):
                raise conflict()
            selected.append(
                ConfiguredModel(
                    organization_public_id=organization_public_id,
                    model_id=ConfiguredModelId(uuid4()),
                    provider_id=provider_id,
                    provider_model_name=candidate.provider_model_name,
                    display_name=candidate.display_name,
                    model_type=candidate.model_type,
                    capabilities=candidate.capabilities,
                    embedding_dimension=candidate.embedding_dimension,
                    enabled=True,
                )
            )
        models = tuple(selected)
        reference = result.provider.credential_reference
        if reference is None:  # guarded by authoritative discovery eligibility
            raise conflict()
        try:
            await self.persistence.create_discovered_models(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                expected_settings=result.provider.settings,
                expected_credential_reference=reference,
                models=models,
            )
        except ModelProviderConfigurationError as exc:
            raise conflict() from exc
        except ModelProviderConflictError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc
        return tuple(
            ConfiguredModelItem(
                model=model, provider_type=result.provider.provider_type
            )
            for model in models
        )

    async def register_manual(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        provider_model_name: str,
        display_name: str,
        model_type: ModelType,
        capabilities: frozenset[ModelCapability],
        embedding_dimension: int | None,
    ) -> tuple[ConfiguredModelItem, ...]:
        await self._authorize(organization_public_id, user_public_id)
        try:
            provider = await get_provider(
                self.persistence,
                organization_public_id=organization_public_id,
                provider_id=OrganizationProviderId(provider_public_id),
            )
            if provider.provider_type not in {
                ProviderType.AZURE_OPENAI,
                ProviderType.OPENAI_COMPATIBLE,
            }:
                raise conflict()
            model = ConfiguredModel(
                organization_public_id=organization_public_id,
                model_id=ConfiguredModelId(uuid4()),
                provider_id=OrganizationProviderId(provider_public_id),
                provider_model_name=provider_model_name,
                display_name=display_name,
                model_type=model_type,
                capabilities=capabilities,
                embedding_dimension=embedding_dimension,
                enabled=True,
            )
            await self.persistence.create_manual_model(
                organization_public_id=organization_public_id,
                model=model,
            )
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc
        return (ConfiguredModelItem(model=model, provider_type=provider.provider_type),)

    async def _authorize(
        self, organization_public_id: UUID, user_public_id: UUID
    ) -> None:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )


@dataclass(frozen=True)
class SetConfiguredModelEnabled:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        model_public_id: UUID,
        enabled: bool,
    ) -> ConfiguredModelItem:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        try:
            result = await self.persistence.set_model_enabled(
                organization_public_id=organization_public_id,
                model_id=ConfiguredModelId(model_public_id),
                enabled=enabled,
            )
            return ConfiguredModelItem(
                model=result.model,
                provider_type=result.provider_type,
            )
        except (ModelProviderConfigurationError, ModelProviderConflictError) as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc


@dataclass(frozen=True)
class DeleteConfiguredModel:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        model_public_id: UUID,
    ) -> None:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        try:
            await self.persistence.delete_model(
                organization_public_id=organization_public_id,
                model_id=ConfiguredModelId(model_public_id),
            )
        except ModelProviderDeleteRestrictedError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc


__all__ = [
    "ConfiguredModelItem",
    "DeleteConfiguredModel",
    "ListConfiguredModels",
    "RegisterConfiguredModels",
    "SetConfiguredModelEnabled",
]
