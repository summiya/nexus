"""Application-facing File persistence boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from nexus.files.domain import File, FileStorageStatus


class FilePersistenceError(Exception):
    """An unexpected File persistence failure occurred."""


class FileReferenceError(Exception):
    """A required File organization or creator reference is invalid."""


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

    async def get_file(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> File | None: ...


__all__ = [
    "FileIdentityConflictError",
    "FileNotReadyError",
    "FilePersistence",
    "FilePersistenceError",
    "FileReferenceError",
    "FileStateConflictError",
]
