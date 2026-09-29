"""Shared authoritative provider-model discovery orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.model_providers.application._shared import enforce_rate_limits, get_provider
from nexus.model_providers.domain import (
    ConfiguredProvider,
    ModelCandidate,
    OrganizationProviderId,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialStore,
    CredentialStoreError,
    ModelProviderPersistence,
    ProviderModelCatalog,
    ProviderModelDiscoveryAuthenticationError,
    ProviderModelDiscoveryRejectedError,
    ProviderModelDiscoveryUnavailableError,
    ProviderModelDiscoveryUnsupportedError,
)
from nexus.ports.rate_limit import RateLimiter, RateLimitError

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProviderDiscoveryPolicy:
    provider_max_requests: int
    provider_window_seconds: int
    organization_max_requests: int
    organization_window_seconds: int


@dataclass(frozen=True)
class ProviderDiscoveryResult:
    provider: ConfiguredProvider
    candidates: tuple[ModelCandidate, ...]


@dataclass(frozen=True)
class ProviderModelDiscovery:
    """Discover candidates and preserve the provider snapshot used for I/O."""

    persistence: ModelProviderPersistence
    credential_store: CredentialStore | None
    catalog: ProviderModelCatalog
    rate_limiter: RateLimiter
    policy: ProviderDiscoveryPolicy

    async def discover(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> ProviderDiscoveryResult:
        provider = await get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        if (
            not provider.enabled
            or provider.validation_status is not ProviderValidationStatus.VALID
            or provider.credential_reference is None
        ):
            raise NexusError(
                ErrorCode.CONFLICT,
                "The provider is not eligible for model discovery.",
            )
        try:
            await enforce_rate_limits(
                self.rate_limiter,
                key_prefix="model-provider-discovery",
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                provider_max_requests=self.policy.provider_max_requests,
                provider_window_seconds=self.policy.provider_window_seconds,
                organization_max_requests=self.policy.organization_max_requests,
                organization_window_seconds=self.policy.organization_window_seconds,
            )
        except RateLimitError as exc:
            logger.warning("model_provider_discovery_rate_limiter_unavailable")
            raise _unavailable() from exc
        store = self.credential_store
        if store is None:
            raise _unavailable()
        try:
            secret = await store.resolve(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                credential_reference=provider.credential_reference,
            )
        except CredentialStoreError as exc:
            raise _unavailable() from exc
        try:
            candidates = await self.catalog.discover(
                provider_type=provider.provider_type,
                settings=provider.settings,
                secret=secret,
            )
        except ProviderModelDiscoveryUnsupportedError as exc:
            raise NexusError(
                ErrorCode.MODEL_DISCOVERY_UNSUPPORTED,
                "Automatic model discovery is not supported for this provider.",
            ) from exc
        except ProviderModelDiscoveryAuthenticationError as exc:
            raise NexusError(
                ErrorCode.CONFLICT,
                "The provider credential cannot be used for model discovery.",
            ) from exc
        except ProviderModelDiscoveryRejectedError as exc:
            raise NexusError(
                ErrorCode.CONFLICT,
                "The provider rejected the model discovery request.",
            ) from exc
        except ProviderModelDiscoveryUnavailableError as exc:
            raise _unavailable() from exc
        return ProviderDiscoveryResult(provider=provider, candidates=candidates)


def _unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "Model discovery is temporarily unavailable.",
        retryable=True,
    )


__all__ = [
    "ProviderDiscoveryPolicy",
    "ProviderDiscoveryResult",
    "ProviderModelDiscovery",
]
