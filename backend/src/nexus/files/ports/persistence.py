"""Application-facing File persistence boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from nexus.files.domain import File


class FilePersistenceError(Exception):
    """An unexpected File persistence failure occurred."""


class FileReferenceError(Exception):
    """A required File organization or creator reference is invalid."""


class FileIdentityConflictError(Exception):
    """Stored File identities or immutable ownership conflict."""


class FilePersistence(Protocol):
    """Short transaction operations used by future File application code."""

    async def create_file(self, file: File) -> None: ...

    async def register_completed_upload(self, file: File) -> None:
        """Create a File once or accept its exact immutable duplicate."""

    async def get_file(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> File | None: ...


__all__ = [
    "FileIdentityConflictError",
    "FilePersistence",
    "FilePersistenceError",
    "FileReferenceError",
]
