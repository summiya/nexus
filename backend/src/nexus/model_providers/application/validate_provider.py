"""Validate one organization model-provider configuration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    authorize,
    conflict,
    credential_unavailable,
    get_provider,
    unavailable,
)
from nexus.model_providers.domain import (
    ConfiguredProvider,
    OrganizationProviderId,
    ProviderValidationStatus,
)
from nexus.model_providers.ports import (
    CredentialStore,
    CredentialStoreError,
    ModelProviderConflictError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
    ProviderConfigurationValidator,
)
from nexus.ports.rate_limit import RateLimiter, RateLimitError

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProviderValidationPolicy:
    provider_max_requests: int
    provider_window_seconds: int
    organization_max_requests: int
    organization_window_seconds: int


@dataclass(frozen=True)
class ValidateModelProvider:
    persistence: ModelProviderPersistence
    permission_checker: PermissionChecker
    credential_store: CredentialStore | None
    validator: ProviderConfigurationValidator
    rate_limiter: RateLimiter
    policy: ProviderValidationPolicy

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
            permission=MANAGE_PERMISSION,
        )
        provider_id = OrganizationProviderId(provider_public_id)
        provider = await get_provider(
            self.persistence,
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )
        await self._enforce_rate_limits(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
        )

        reference = provider.credential_reference
        if reference is None:
            status = ProviderValidationStatus.UNSUPPORTED_CONFIGURATION
        else:
            store = self.credential_store
            if store is None:
                raise credential_unavailable()
            try:
                secret = await store.resolve(
                    organization_public_id=organization_public_id,
                    provider_id=provider_id,
                    credential_reference=reference,
                )
            except CredentialStoreError as exc:
                raise credential_unavailable() from exc
            status = await self.validator.validate(
                provider_type=provider.provider_type,
                settings=provider.settings,
                secret=secret,
            )

        try:
            updated = await self.persistence.record_provider_validation(
                organization_public_id=organization_public_id,
                provider_id=provider_id,
                expected_settings=provider.settings,
                expected_credential_reference=reference,
                status=status,
            )
        except ModelProviderConflictError as exc:
            raise conflict() from exc
        except ModelProviderReferenceError as exc:
            raise NexusError(
                ErrorCode.NOT_FOUND,
                "The requested resource was not found.",
            ) from exc
        except ModelProviderPersistenceError as exc:
            raise unavailable() from exc

        logger.info(
            "model_provider_validation_completed",
            organization_public_id=str(organization_public_id),
            actor_user_public_id=str(user_public_id),
            provider_public_id=str(provider_public_id),
            validation_status=status.value,
        )
        return updated

    async def _enforce_rate_limits(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
    ) -> None:
        limits = (
            (
                f"model-provider-validation:organization:{organization_public_id}",
                self.policy.organization_max_requests,
                self.policy.organization_window_seconds,
            ),
            (
                (
                    "model-provider-validation:provider:"
                    f"{organization_public_id}:{provider_id.value}"
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
            logger.warning("model_provider_validation_rate_limiter_unavailable")
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The service is temporarily unavailable.",
                retryable=True,
            ) from exc


__all__ = ["ProviderValidationPolicy", "ValidateModelProvider"]
