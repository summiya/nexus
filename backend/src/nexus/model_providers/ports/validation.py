"""Provider-neutral configured-provider validation capability."""

from __future__ import annotations

from typing import Protocol

from nexus.model_providers.domain import (
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
    ProviderValidationStatus,
)


class ProviderConfigurationValidator(Protocol):
    """Validate one provider configuration without exposing transport details."""

    async def validate(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> ProviderValidationStatus: ...


__all__ = ["ProviderConfigurationValidator"]
