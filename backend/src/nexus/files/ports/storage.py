"""Provider-neutral object storage boundary for File binary content."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Protocol


class ObjectStorageError(Exception):
    """An unexpected object storage failure occurred."""


class ObjectStorageAlreadyExistsError(ObjectStorageError):
    """The requested storage key already exists."""


class ObjectStorageNotFoundError(ObjectStorageError):
    """The requested storage key does not exist."""


class ObjectStorage(Protocol):
    """Provider-neutral streamed storage operations used by the File capability."""

    async def create_object(
        self,
        *,
        storage_key: str,
        content: AsyncIterable[bytes],
    ) -> None:
        """Create a new object atomically from a single-pass byte stream."""

    def stream_object(
        self,
        *,
        storage_key: str,
    ) -> AsyncIterator[bytes]:
        """Return a lazy byte stream; storage errors may arise during iteration."""

    async def delete_object(self, *, storage_key: str) -> None:
        """Delete an object, succeeding when it is already absent."""


__all__ = [
    "ObjectStorage",
    "ObjectStorageAlreadyExistsError",
    "ObjectStorageError",
    "ObjectStorageNotFoundError",
]
