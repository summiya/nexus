"""Application-facing File persistence boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from nexus.files.domain import File, FileStorageStatus


@dataclass(frozen=True)
class FileDeletionTarget:
    """Minimal provider-neutral data required to resume one File deletion."""

    storage_key: str = field(repr=False)


class FilePersistenceError(Exception):
    """An unexpected File persistence failure occurred."""


class FileReferenceError(Exception):
    """A required File organization or creator reference is invalid."""


class FileDeletionInProgressError(Exception):
    """A malware result arrived while the File is being deleted."""


class FileIdentityConflictError(Exception):
    """Stored File identities or immutable ownership conflict."""


class FileNotReadyError(FilePersistenceError):
    """A File row required by an asynchronous follow-up is not visible yet."""


class FileStateConflictError(Exception):
    """A File terminal state conflicts with the requested lifecycle transition."""


class FilePersistence(Protocol):
    """Short transaction operations used by File application code."""

    async def create_file(self, file: File) -> None: ...

    async def register_completed_upload(self, file: File) -> None:
        """Create a File once or accept its exact immutable duplicate."""

    async def apply_malware_scan_result(
        self,
        *,
        storage_key: str,
        target_status: FileStorageStatus,
        updated_at: datetime,
    ) -> None:
        """Apply one idempotent terminal malware-scan state transition."""

    async def prepare_file_deletion(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
        updated_at: datetime,
    ) -> FileDeletionTarget | None:
        """Mark one tenant File DELETING or resume an existing deletion."""

    async def delete_file_record(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> None:
        """Delete metadata only after the File is already DELETING."""

    async def get_file(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> File | None: ...

    async def list_files(
        self,
        *,
        organization_public_id: UUID,
        before_created_at: datetime | None,
        before_public_id: UUID | None,
        limit: int,
    ) -> tuple[File, ...]:
        """List one keyset page in newest-first deterministic order."""


__all__ = [
    "FileDeletionInProgressError",
    "FileDeletionTarget",
    "FileIdentityConflictError",
    "FileNotReadyError",
    "FilePersistence",
    "FilePersistenceError",
    "FileReferenceError",
    "FileStateConflictError",
]
