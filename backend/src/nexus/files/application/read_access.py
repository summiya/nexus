"""Shared authorization policy for File metadata reads."""

from __future__ import annotations

from uuid import UUID

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.errors import ErrorCode, NexusError

FILES_READ_PERMISSION = "files.read"


async def authorize_files_read(
    permission_checker: PermissionChecker,
    *,
    organization_public_id: UUID,
    user_public_id: UUID,
) -> None:
    try:
        allowed = await permission_checker.has_permission(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            permission_key=FILES_READ_PERMISSION,
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


__all__ = ["FILES_READ_PERMISSION", "authorize_files_read"]
