"""Get one configured model provider."""

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.model_providers.application._shared import (
    READ_PERMISSION,
    authorize,
    get_provider,
)
from nexus.model_providers.domain import ConfiguredProvider, OrganizationProviderId
from nexus.model_providers.ports import ModelProviderPersistence


@dataclass(frozen=True)
class GetModelProvider:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
    ) -> ConfiguredProvider:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=READ_PERMISSION,
        )
        return await get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=OrganizationProviderId(provider_public_id),
        )


__all__ = ["GetModelProvider"]
