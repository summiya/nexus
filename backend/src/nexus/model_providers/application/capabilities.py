"""Effective provider-management capabilities for one authenticated actor."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.model_providers.application._shared import (
    MANAGE_PERMISSION,
    READ_PERMISSION,
)


@dataclass(frozen=True)
class ModelProviderCapabilities:
    can_read: bool
    can_manage: bool


@dataclass(frozen=True)
class GetModelProviderCapabilities:
    """Project focused capability flags without exposing role internals."""

    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> ModelProviderCapabilities:
        try:
            can_read = await self.permission_checker.has_permission(
                organization_public_id=organization_public_id,
                user_public_id=user_public_id,
                permission_key=READ_PERMISSION,
            )
            can_manage = await self.permission_checker.has_permission(
                organization_public_id=organization_public_id,
                user_public_id=user_public_id,
                permission_key=MANAGE_PERMISSION,
            )
        except PermissionCheckError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Authorization is temporarily unavailable.",
                retryable=True,
            ) from exc
        return ModelProviderCapabilities(can_read=can_read, can_manage=can_manage)


__all__ = ["GetModelProviderCapabilities", "ModelProviderCapabilities"]
