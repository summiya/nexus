"""Application-facing File persistence boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from nexus.files.domain import File, FileUploadAttempt


class FilePersistenceError(Exception):
    """An unexpected File persistence failure occurred."""


class FileReferenceError(Exception):
    """A required File organization or creator reference is invalid."""


class FilePersistence(Protocol):
    """Short transaction operations used by future File application code."""

    async def create_file(self, file: File) -> None: ...

    async def create_pending_upload(
        self,
        *,
        file: File,
        upload_attempt: FileUploadAttempt,
    ) -> None: ...

    async def get_file(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> File | None: ...


__all__ = ["FilePersistence", "FilePersistenceError", "FileReferenceError"]
