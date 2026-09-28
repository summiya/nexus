"""Create one configured model provider."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    NOT_FOUND,
    authorize,
    conflict,
    unavailable,
)
from nexus.model_providers.domain import (
    ConfiguredProvider,
    ModelProviderConfigurationError,
    OrganizationProviderId,
    ProviderType,
    provider_settings_from_mapping,
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)


@dataclass(frozen=True)
class CreateModelProvider:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_type: ProviderType,
        display_name: str,
        settings: Mapping[str, str],
        enabled: bool,
    ) -> ConfiguredProvider:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        try:
            provider = ConfiguredProvider(
                organization_public_id=organization_public_id,
                provider_id=OrganizationProviderId(uuid4()),
                provider_type=provider_type,
                display_name=display_name,
                settings=provider_settings_from_mapping(provider_type, settings),
                enabled=enabled,
            )
            await self.persistence.create_provider(provider)
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc
        return provider


__all__ = ["CreateModelProvider"]
