"""Enable or disable one configured model provider."""

from dataclasses import dataclass
from uuid import UUID

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
)
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)


@dataclass(frozen=True)
class SetModelProviderEnabled:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
        enabled: bool,
    ) -> ConfiguredProvider:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        try:
            return await self.persistence.set_provider_enabled(
                organization_public_id=organization_public_id,
                provider_id=OrganizationProviderId(provider_public_id),
                enabled=enabled,
            )
        except ModelProviderConfigurationError as exc:
            raise NexusError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ModelProviderConflictError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc


__all__ = ["SetModelProviderEnabled"]
