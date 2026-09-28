"""Authorized organization model-provider management orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import assert_never
from uuid import UUID, uuid4

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.model_providers.domain import (
    AnthropicSettings,
    AzureOpenAISettings,
    ConfiguredProvider,
    CredentialReference,
    GeminiSettings,
    ModelProviderConfigurationError,
    OpenAICompatibleSettings,
    OpenAISettings,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
)
from nexus.model_providers.ports import (
    CredentialStore,
    CredentialStoreConflictError,
    CredentialStoreError,
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
    ProviderUpdateResult,
    credential_storage_name,
)

_READ_PERMISSION = "model_providers.read"
_MANAGE_PERMISSION = "model_providers.manage"
_NOT_FOUND = "The requested resource was not found."
_UNAVAILABLE = "Model provider configuration is temporarily unavailable."
_CREDENTIAL_UNAVAILABLE = "Provider credential storage is temporarily unavailable."

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReadModelProviders:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def list(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> tuple[ConfiguredProvider, ...]:
        await _authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=_READ_PERMISSION,
        )
        configuration = await _load_configuration(
            self.persistence,
            organization_public_id=organization_public_id,
        )
        return configuration.providers if configuration is not None else ()

    async def get(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
    ) -> ConfiguredProvider:
        await _authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=_READ_PERMISSION,
        )
        return await _get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=OrganizationProviderId(provider_public_id),
        )


@dataclass(frozen=True)
class ManageModelProviders:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    credential_store: CredentialStore | None

    async def create(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_type: ProviderType,
        display_name: str,
        settings: Mapping[str, str],
        enabled: bool,
    ) -> ConfiguredProvider:
        await self._authorize(organization_public_id, user_public_id)
        try:
            provider = ConfiguredProvider(
                organization_public_id=organization_public_id,
                provider_id=OrganizationProviderId(uuid4()),
                provider_type=provider_type,
                display_name=display_name,
                settings=_provider_settings(provider_type, settings),
                enabled=enabled,
            )
            await self.persistence.create_provider(provider)
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise _conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise _unavailable() from exc
        return provider

    async def update(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        display_name: str,
        settings: Mapping[str, str],
    ) -> ConfiguredProvider:
        await self._authorize(organization_public_id, user_public_id)
        provider_id = OrganizationProviderId(provider_public_id)
        existing = await _get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        try:
            replacement = replace(
                existing,
                display_name=display_name,
                settings=_provider_settings(existing.provider_type, settings),
            )
            if (
                _provider_url(existing) != _provider_url(replacement)
                and existing.credential_reference is not None
                and self.credential_store is None
            ):
                raise _credential_unavailable()
            result = await self.persistence.update_provider(replacement)
        except NexusError:
            raise
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise _conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise _unavailable() from exc

        await self._cleanup_cleared_credential(
            result,
            organization_public_id=organization_public_id,
            actor_user_public_id=user_public_id,
        )
        return result.provider

    async def set_enabled(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        enabled: bool,
    ) -> ConfiguredProvider:
        await self._authorize(organization_public_id, user_public_id)
        provider = await _get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=OrganizationProviderId(provider_public_id),
        )
        try:
            result = await self.persistence.update_provider(
                replace(provider, enabled=enabled)
            )
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise _conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise _unavailable() from exc
        return result.provider

    async def set_credential(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        secret: ProviderCredentialSecret,
    ) -> ConfiguredProvider:
        await self._authorize(organization_public_id, user_public_id)
        store = self.credential_store
        if store is None:
            raise _credential_unavailable()
        provider_id = OrganizationProviderId(provider_public_id)
        provider = await _get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        old_reference = provider.credential_reference
        new_reference = CredentialReference(uuid4())
        try:
            await store.put(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                credential_reference=new_reference,
                secret=secret,
            )
        except CredentialStoreConflictError as exc:
            raise _conflict() from exc
        except CredentialStoreError as exc:
            raise _credential_unavailable() from exc

        try:
            updated = await self.persistence.set_provider_credential_reference(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                expected_credential_reference=old_reference,
                credential_reference=new_reference,
            )
        except (
            ModelProviderConflictError,
            ModelProviderReferenceError,
            ModelProviderPersistenceError,
            ModelProviderConfigurationError,
        ) as exc:
            await self._delete_credential_best_effort(
                organization_public_id=organization_public_id,
                actor_user_public_id=user_public_id,
                provider_id=provider_id,
                credential_reference=new_reference,
                reason="credential_switch_compensation",
            )
            if isinstance(exc, ModelProviderConflictError):
                raise _conflict() from exc
            if isinstance(exc, ModelProviderReferenceError):
                raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND) from exc
            if isinstance(exc, ModelProviderConfigurationError):
                raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
            raise _unavailable() from exc

        if old_reference is not None:
            await self._delete_credential_best_effort(
                organization_public_id=organization_public_id,
                actor_user_public_id=user_public_id,
                provider_id=provider_id,
                credential_reference=old_reference,
                reason="credential_replacement_cleanup",
            )
            event = "model_provider_credential_replaced"
        else:
            event = "model_provider_credential_set"
        logger.info(
            event,
            organization_public_id=str(organization_public_id),
            actor_user_public_id=str(user_public_id),
            provider_public_id=str(provider_id.value),
        )
        return updated

    async def delete(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
    ) -> None:
        await self._authorize(organization_public_id, user_public_id)
        provider_id = OrganizationProviderId(provider_public_id)
        existing = await _get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        if existing.credential_reference is not None and self.credential_store is None:
            raise _credential_unavailable()
        try:
            deleted = await self.persistence.delete_provider(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
            )
        except ModelProviderDeleteRestrictedError as exc:
            raise _conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise _unavailable() from exc
        if deleted.credential_reference is not None:
            cleanup_succeeded = await self._delete_credential_best_effort(
                organization_public_id=organization_public_id,
                actor_user_public_id=user_public_id,
                provider_id=provider_id,
                credential_reference=deleted.credential_reference,
                reason="provider_delete_cleanup",
            )
            if cleanup_succeeded:
                logger.info(
                    "model_provider_credential_deleted",
                    organization_public_id=str(organization_public_id),
                    actor_user_public_id=str(user_public_id),
                    provider_public_id=str(provider_public_id),
                )

    async def _authorize(
        self, organization_public_id: UUID, user_public_id: UUID
    ) -> None:
        await _authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=_MANAGE_PERMISSION,
        )

    async def _cleanup_cleared_credential(
        self,
        result: ProviderUpdateResult,
        *,
        organization_public_id: UUID,
        actor_user_public_id: UUID,
    ) -> None:
        reference = result.cleared_credential_reference
        if reference is None:
            return
        cleanup_succeeded = await self._delete_credential_best_effort(
            organization_public_id=organization_public_id,
            actor_user_public_id=actor_user_public_id,
            provider_id=result.provider.provider_id,
            credential_reference=reference,
            reason="provider_url_change_cleanup",
        )
        if cleanup_succeeded:
            logger.info(
                "model_provider_credential_deleted",
                organization_public_id=str(organization_public_id),
                actor_user_public_id=str(actor_user_public_id),
                provider_public_id=str(result.provider.provider_id.value),
            )

    async def _delete_credential_best_effort(
        self,
        *,
        organization_public_id: UUID,
        actor_user_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
        reason: str,
    ) -> bool:
        store = self.credential_store
        storage_name = credential_storage_name(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
            credential_reference=credential_reference,
        )
        if store is not None:
            try:
                await store.delete(
                    organization_public_id=organization_public_id,
                    provider_id=provider_id,
                    credential_reference=credential_reference,
                )
                return True
            except CredentialStoreError:
                pass
        logger.warning(
            "model_provider_credential_cleanup_failed",
            organization_public_id=str(organization_public_id),
            actor_user_public_id=str(actor_user_public_id),
            provider_public_id=str(provider_id.value),
            orphan_storage_name=storage_name,
            cleanup_reason=reason,
        )
        return False


async def _authorize(
    checker: PermissionChecker,
    *,
    organization_public_id: UUID,
    user_public_id: UUID,
    permission: str,
) -> None:
    try:
        allowed = await checker.has_permission(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission_key=permission,
        )
    except PermissionCheckError as exc:
        raise NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Authorization is temporarily unavailable.",
            retryable=True,
        ) from exc
    if not allowed:
        raise NexusError(
            ErrorCode.FORBIDDEN,
            "You are not allowed to perform this action.",
        )


async def _load_configuration(
    persistence: ModelProviderPersistence,
    *,
    organization_public_id: UUID,
) -> OrganizationModelProviderConfiguration | None:
    try:
        return await persistence.load_configuration(
            organization_public_id=organization_public_id
        )
    except ModelProviderPersistenceError as exc:
        raise _unavailable() from exc


async def _get_provider(
    persistence: ModelProviderPersistence,
    *,
    organization_public_id: UUID,
    provider_id: OrganizationProviderId,
) -> ConfiguredProvider:
    configuration = await _load_configuration(
        persistence,
        organization_public_id=organization_public_id,
    )
    if configuration is not None:
        for provider in configuration.providers:
            if provider.provider_id == provider_id:
                return provider
    raise NexusError(ErrorCode.NOT_FOUND, _NOT_FOUND)


def _provider_settings(
    provider_type: ProviderType,
    values: Mapping[str, str],
) -> ProviderSettings:
    expected_keys: set[str]
    if provider_type is ProviderType.OPENAI:
        expected_keys = set()
        factory: ProviderSettings = OpenAISettings()
    elif provider_type is ProviderType.ANTHROPIC:
        expected_keys = set()
        factory = AnthropicSettings()
    elif provider_type is ProviderType.GEMINI:
        expected_keys = set()
        factory = GeminiSettings()
    elif provider_type is ProviderType.AZURE_OPENAI:
        expected_keys = {"endpoint", "api_version"}
        if set(values) != expected_keys:
            raise ModelProviderConfigurationError("Provider settings are invalid.")
        return AzureOpenAISettings(
            endpoint=values["endpoint"],
            api_version=values["api_version"],
        )
    elif provider_type is ProviderType.OPENAI_COMPATIBLE:
        expected_keys = {"base_url"}
        if set(values) != expected_keys:
            raise ModelProviderConfigurationError("Provider settings are invalid.")
        return OpenAICompatibleSettings(base_url=values["base_url"])
    else:
        assert_never(provider_type)
    if set(values) != expected_keys:
        raise ModelProviderConfigurationError("Provider settings are invalid.")
    return factory


def _provider_url(provider: ConfiguredProvider) -> str | None:
    if isinstance(provider.settings, AzureOpenAISettings):
        return provider.settings.endpoint
    if isinstance(provider.settings, OpenAICompatibleSettings):
        return provider.settings.base_url
    return None


def _conflict() -> NexusError:
    return NexusError(
        ErrorCode.CONFLICT,
        "The request conflicts with the current provider configuration.",
    )


def _unavailable() -> NexusError:
    return NexusError(ErrorCode.SERVICE_UNAVAILABLE, _UNAVAILABLE, retryable=True)


def _credential_unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        _CREDENTIAL_UNAVAILABLE,
        retryable=True,
    )


__all__ = ["ManageModelProviders", "ReadModelProviders"]
