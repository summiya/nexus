"""Partially update one configured model provider."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.model_providers.application._credential_lifecycle import (
    delete_credential_best_effort,
    settle_before_cancellation,
)
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    NOT_FOUND,
    authorize,
    conflict,
    credential_unavailable,
    get_provider,
    provider_settings,
    unavailable,
)
from nexus.model_providers.domain import (
    AzureOpenAISettings,
    ConfiguredProvider,
    ModelProviderConfigurationError,
    OpenAICompatibleSettings,
    OrganizationProviderId,
    ProviderSettings,
)
from nexus.model_providers.ports import (
    CredentialStore,
    ModelProviderConflictError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class UpdateModelProvider:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    credential_store: CredentialStore | None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        display_name: str | None,
        settings: Mapping[str, str] | None,
    ) -> ConfiguredProvider:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        provider_id = OrganizationProviderId(provider_public_id)
        parsed_settings: ProviderSettings | None = None
        if settings is not None:
            existing = await get_provider(
                self.persistence,
                organization_public_id=organization_public_id,
                provider_id=provider_id,
            )
            try:
                parsed_settings = provider_settings(existing.provider_type, settings)
            except ModelProviderConfigurationError as exc:
                raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
            if (
                existing.credential_reference is not None
                and _provider_url(parsed_settings)
                != _provider_url(existing.settings)
                and self.credential_store is None
            ):
                raise credential_unavailable()

        return await settle_before_cancellation(
            self._update_and_cleanup(
                organization_public_id=organization_public_id,
                actor_user_public_id=user_public_id,
                provider_id=provider_id,
                display_name=display_name,
                settings=parsed_settings,
            )
        )

    async def _update_and_cleanup(
        self,
        *,
        organization_public_id: UUID,
        actor_user_public_id: UUID,
        provider_id: OrganizationProviderId,
        display_name: str | None,
        settings: ProviderSettings | None,
    ) -> ConfiguredProvider:
        try:
            result = await self.persistence.update_provider_configuration(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                display_name=display_name,
                settings=settings,
            )
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc

        reference = result.cleared_credential_reference
        if reference is not None:
            cleanup_succeeded = await delete_credential_best_effort(
                self.credential_store,
                organization_public_id=organization_public_id,
                actor_user_public_id=actor_user_public_id,
                provider_id=provider_id,
                credential_reference=reference,
                reason="provider_url_change_cleanup",
            )
            if cleanup_succeeded:
                logger.info(
                    "model_provider_credential_deleted",
                    organization_public_id=str(organization_public_id),
                    actor_user_public_id=str(actor_user_public_id),
                    provider_public_id=str(provider_id.value),
                )
        return result.provider


def _provider_url(settings: ProviderSettings) -> str | None:
    if isinstance(settings, AzureOpenAISettings):
        return settings.endpoint
    if isinstance(settings, OpenAICompatibleSettings):
        return settings.base_url
    return None


__all__ = ["UpdateModelProvider"]
