"""Shared model-provider application boundary helpers."""

from __future__ import annotations

from uuid import UUID

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.domain import (
    ConfiguredProvider,
    OrganizationModelProviderConfiguration,
    OrganizationProviderId,
)
from nexus.model_providers.ports import (
    ModelProviderPersistence,
    ModelProviderPersistenceError,
)

READ_PERMISSION = "model_providers.read"
MANAGE_PERMISSION = "model_providers.manage"
NOT_FOUND = "The requested resource was not found."
CREDENTIAL_UNAVAILABLE = "Provider credential storage is temporarily unavailable."


async def authorize(
    checker: PermissionChecker,
    *,
    organization_public_id: UUID,
    user_public_id: UUID,
    permission: str,
) -> None:
    try:
        allowed = await checker.has_permission(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission_key=permission,
        )
    except PermissionCheckError as exc:
        raise NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Authorization is temporarily unavailable.",
            retryable=True,
        ) from exc
    if not allowed:
        raise NexusError(
            ErrorCode.FORBIDDEN,
            "You are not allowed to perform this action.",
        )


async def load_configuration(
    persistence: ModelProviderPersistence,
    *,
    organization_public_id: UUID,
) -> OrganizationModelProviderConfiguration | None:
    try:
        return await persistence.load_configuration(
            organization_public_id=organization_public_id
        )
    except ModelProviderPersistenceError as exc:
        raise unavailable() from exc


async def get_provider(
    persistence: ModelProviderPersistence,
    *,
    organization_public_id: UUID,
    provider_id: OrganizationProviderId,
) -> ConfiguredProvider:
    configuration = await load_configuration(
        persistence,
        organization_public_id=organization_public_id,
    )
    if configuration is not None:
        for provider in configuration.providers:
            if provider.provider_id == provider_id:
                return provider
    raise NexusError(ErrorCode.NOT_FOUND, NOT_FOUND)


def conflict() -> NexusError:
    return NexusError(
        ErrorCode.CONFLICT,
        "The request conflicts with the current provider configuration.",
    )


def unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "Model provider configuration is temporarily unavailable.",
        retryable=True,
    )


def credential_unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        CREDENTIAL_UNAVAILABLE,
        retryable=True,
    )
