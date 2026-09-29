"""Discover safely classified models for one configured provider."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.model_providers.application._shared import authorize, get_provider
from nexus.model_providers.domain import (
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
    ProviderModelDiscoveryUnavailableError,
    ProviderModelDiscoveryUnsupportedError,
)
from nexus.ports.rate_limit import RateLimiter, RateLimitError

logger = get_logger(__name__)

_MANAGE_PERMISSION = "model_providers.manage"


@dataclass(frozen=True)
class ProviderDiscoveryPolicy:
    provider_max_requests: int
    provider_window_seconds: int
    organization_max_requests: int
    organization_window_seconds: int


@dataclass(frozen=True)
class DiscoverProviderModels:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    credential_store: CredentialStore | None
    catalog: ProviderModelCatalog
    rate_limiter: RateLimiter
    policy: ProviderDiscoveryPolicy

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
            permission=_MANAGE_PERMISSION,
        )
        provider_id = OrganizationProviderId(provider_public_id)
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
        await self._enforce_rate_limits(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        store = self.credential_store
        if store is None:
            raise self._unavailable()
        try:
            secret = await store.resolve(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                credential_reference=provider.credential_reference,
            )
        except CredentialStoreError as exc:
            raise self._unavailable() from exc
        try:
            return await self.catalog.discover(
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
        except ProviderModelDiscoveryUnavailableError as exc:
            raise self._unavailable() from exc

    async def _enforce_rate_limits(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> None:
        limits = (
            (
                f"model-provider-discovery:organization:{organization_public_id}",
                self.policy.organization_max_requests,
                self.policy.organization_window_seconds,
            ),
            (
                (
                    f"model-provider-discovery:provider:{organization_public_id}:"
                    f"{provider_id.value}"
                ),
                self.policy.provider_max_requests,
                self.policy.provider_window_seconds,
            ),
        )
        try:
            for key, limit, window_seconds in limits:
                if not await self.rate_limiter.allow(
                    key=key,
                    limit=limit,
                    window_seconds=window_seconds,
                ):
                    raise NexusError(
                        ErrorCode.RATE_LIMITED,
                        "Too many requests. Please try again later.",
                        retryable=True,
                    )
        except RateLimitError as exc:
            logger.warning("model_provider_discovery_rate_limiter_unavailable")
            raise self._unavailable() from exc

    @staticmethod
    def _unavailable() -> NexusError:
        return NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Model discovery is temporarily unavailable.",
            retryable=True,
        )


__all__ = ["DiscoverProviderModels", "ProviderDiscoveryPolicy"]
