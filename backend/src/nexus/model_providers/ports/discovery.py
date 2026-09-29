"""Provider-neutral model discovery boundary."""

from __future__ import annotations

from typing import Protocol

from nexus.model_providers.domain import (
    ModelCandidate,
    ProviderCredentialSecret,
    ProviderSettings,
    ProviderType,
)


class ProviderModelCatalogError(RuntimeError):
    """Base error for sanitized provider discovery failures."""


class ProviderModelDiscoveryAuthenticationError(ProviderModelCatalogError):
    """The provider rejected the configured credential."""


class ProviderModelDiscoveryUnsupportedError(ProviderModelCatalogError):
    """Automatic discovery is unavailable for this provider configuration."""


class ProviderModelDiscoveryUnavailableError(ProviderModelCatalogError):
    """The provider catalog is temporarily unavailable or unusable."""


class ProviderModelCatalog(Protocol):
    """Discover safely classified models available to one provider credential."""

    async def discover(
        self,
        *,
        provider_type: ProviderType,
        settings: ProviderSettings,
        secret: ProviderCredentialSecret,
    ) -> tuple[ModelCandidate, ...]: ...


__all__ = [
    "ProviderModelCatalog",
    "ProviderModelCatalogError",
    "ProviderModelDiscoveryAuthenticationError",
    "ProviderModelDiscoveryUnavailableError",
    "ProviderModelDiscoveryUnsupportedError",
]
