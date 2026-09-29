"""Discover safely classified models for one configured provider."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.model_providers.application._provider_model_discovery import (
    ProviderDiscoveryPolicy,
    ProviderModelDiscovery,
)
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    authorize,
)
from nexus.model_providers.domain import ModelCandidate, OrganizationProviderId


@dataclass(frozen=True)
class DiscoverProviderModels:
    permission_checker: PermissionChecker
    discovery: ProviderModelDiscovery

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        provider_public_id: UUID,
    ) -> tuple[ModelCandidate, ...]:
        await authorize(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission=MANAGE_PERMISSION,
        )
        result = await self.discovery.discover(
            organization_public_id=organization_public_id,
            provider_id=OrganizationProviderId(provider_public_id),
        )
        return result.candidates


__all__ = ["DiscoverProviderModels", "ProviderDiscoveryPolicy"]
