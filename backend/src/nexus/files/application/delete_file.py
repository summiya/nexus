"""Delete one File without losing recovery metadata before Blob deletion."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from nexus.authorization import PermissionChecker
from nexus.errors import ErrorCode, NexusError
from nexus.files.application.delete_access import authorize_files_delete
from nexus.files.ports import FilePersistence, FilePersistenceError, ObjectStorage, ObjectStorageError
from nexus.logging import get_logger

_SAFE_CORRELATION_LENGTH = 16
_DELETE_UNAVAILABLE_MESSAGE = "The file could not be deleted."

logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DeleteFile:
    """Mark deleting, remove the Blob, then remove metadata in separate transactions."""

    persistence: FilePersistence
    permission_checker: PermissionChecker
    object_storage: ObjectStorage
    clock: Callable[[], datetime] = _utc_now

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> None:
        await authorize_files_delete(
            self.permission_checker,
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
        )

        correlation = _safe_correlation(
            organization_public_id=organization_public_id,
            file_public_id=file_public_id,
        )
        try:
            target = await self.persistence.prepare_file_deletion(
                organization_public_id=organization_public_id,
                file_public_id=file_public_id,
                updated_at=self.clock(),
            )
        except FilePersistenceError as exc:
            logger.warning("file_delete_prepare_failed", correlation=correlation)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                _DELETE_UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from exc

        if target is None:
            raise NexusError(
                ErrorCode.NOT_FOUND,
                "The requested resource was not found.",
            )

        try:
            await self.object_storage.delete_object(storage_key=target.storage_key)
        except ObjectStorageError as exc:
            logger.warning("file_delete_storage_failed", correlation=correlation)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                _DELETE_UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from exc

        try:
            await self.persistence.delete_file_record(
                organization_public_id=organization_public_id,
                file_public_id=file_public_id,
            )
        except FilePersistenceError as exc:
            logger.warning("file_delete_finalize_failed", correlation=correlation)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                _DELETE_UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from exc

        logger.info("file_deleted", correlation=correlation)


def _safe_correlation(*, organization_public_id: UUID, file_public_id: UUID) -> str:
    value = f"{organization_public_id}\0{file_public_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_SAFE_CORRELATION_LENGTH]


__all__ = ["DeleteFile"]
