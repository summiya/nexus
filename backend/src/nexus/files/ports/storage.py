"""Provider-neutral object storage boundary for File binary content."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


class ObjectStorageError(Exception):
    """An unexpected object storage failure occurred."""


class ObjectStorageAlreadyExistsError(ObjectStorageError):
    """The requested storage key already exists."""


class ObjectStorageNotFoundError(ObjectStorageError):
    """The requested storage key does not exist."""


@dataclass(frozen=True, repr=False)
class StoredObjectProperties:
    """Provider-neutral current properties for one stored object."""

    entity_tag: str
    size_bytes: int
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.entity_tag, str) or not self.entity_tag:
            raise ValueError("entity_tag is invalid")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.metadata.items()
        ):
            raise TypeError("metadata must contain string keys and values")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


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

    async def get_object_properties(
        self,
        *,
        storage_key: str,
    ) -> StoredObjectProperties:
        """Read current object identity, size, and metadata."""


__all__ = [
    "ObjectStorage",
    "ObjectStorageAlreadyExistsError",
    "ObjectStorageError",
    "ObjectStorageNotFoundError",
    "StoredObjectProperties",
]
