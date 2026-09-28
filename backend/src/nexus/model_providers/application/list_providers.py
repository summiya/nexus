"""List configured model providers for one organization."""

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.model_providers.application._shared import (
    READ_PERMISSION,
    authorize,
    load_configuration,
)
from nexus.model_providers.domain import ConfiguredProvider
from nexus.model_providers.ports import ModelProviderPersistence


@dataclass(frozen=True)
class ListModelProviders:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> tuple[ConfiguredProvider, ...]:
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
        return configuration.providers if configuration is not None else ()


__all__ = ["ListModelProviders"]
