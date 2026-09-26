"""Retrieve one authorized tenant-scoped File."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.files.application.list_files import _authorize_files_read
from nexus.files.domain import File
from nexus.files.ports import FilePersistence, FilePersistenceError


@dataclass(frozen=True)
class GetFile:
    """Authorize and retrieve one File without cross-tenant disclosure."""

    persistence: FilePersistence
    permission_checker: PermissionChecker

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> File:
        await _authorize_files_read(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
        )
        try:
            file = await self.persistence.get_file(
                organization_public_id=organization_public_id,
                file_public_id=file_public_id,
            )
        except FilePersistenceError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The file could not be retrieved.",
                retryable=True,
            ) from exc

        if file is None:
            raise NexusError(
                ErrorCode.NOT_FOUND,
                "The requested resource was not found.",
            )
        return file


__all__ = ["GetFile"]
