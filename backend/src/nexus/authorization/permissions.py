"""Provider-neutral runtime permission-checking boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class PermissionCheckError(Exception):
    """An unexpected permission-checking failure occurred."""


class PermissionChecker(Protocol):
    """Check one permission for a trusted organization and user identity."""

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool: ...


__all__ = ["PermissionCheckError", "PermissionChecker"]
