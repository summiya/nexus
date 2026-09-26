"""Azure Blob Storage implementation of the object storage boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobType
from azure.storage.blob.aio import ContainerClient

from nexus.files.ports import (
    ObjectStorageAlreadyExistsError,
    ObjectStorageError,
    ObjectStorageNotFoundError,
    StoredObjectProperties,
)

_ALREADY_EXISTS_MESSAGE = "The object already exists in storage."
_NOT_FOUND_MESSAGE = "The object was not found in storage."
_STORAGE_FAILURE_MESSAGE = "The object storage operation failed."


class _TrackedUploadContent:
    """Stream caller content while retaining failures raised by its producer."""

    def __init__(self, content: AsyncIterable[bytes]) -> None:
        self._content = content
        self._source_failure: BaseException | None = None

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._content:
                yield chunk
        except BaseException as exc:
            self._source_failure = exc
            raise


async def _await_provider_operation[T](awaitable: Awaitable[T]) -> T:
    """Let an in-flight provider operation settle before propagating cancellation."""
    operation = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                continue
        if not operation.cancelled():
            operation.exception()
        raise


class AzureBlobObjectStorage:
    """Provider-neutral object operations backed by a borrowed ContainerClient."""

    def __init__(self, container_client: ContainerClient) -> None:
        self._container_client = container_client

    async def create_object(
        self,
        *,
        storage_key: str,
        content: AsyncIterable[bytes],
    ) -> None:
        """Create an immutable Block Blob without replacing an existing object."""
        tracked_content = _TrackedUploadContent(content)
        try:
            await self._container_client.upload_blob(
                name=storage_key,
                data=tracked_content,
                blob_type=BlobType.BLOCKBLOB,
                overwrite=False,
            )
        except AzureError as exc:
            if tracked_content._source_failure is exc:
                raise
            if tracked_content._source_failure is not None:
                raise tracked_content._source_failure from exc
            if isinstance(exc, ResourceExistsError):
                raise ObjectStorageAlreadyExistsError(_ALREADY_EXISTS_MESSAGE) from exc
            raise ObjectStorageError(_STORAGE_FAILURE_MESSAGE) from exc

    def stream_object(self, *, storage_key: str) -> AsyncIterator[bytes]:
        """Return a lazy stream of bytes from Azure Blob Storage."""
        return self._stream_object(storage_key=storage_key)

    async def _stream_object(self, *, storage_key: str) -> AsyncIterator[bytes]:
        try:
            downloader = await _await_provider_operation(
                self._container_client.download_blob(storage_key)
            )
            chunks = downloader.chunks()
            while True:
                try:
                    chunk = await _await_provider_operation(anext(chunks))
                except StopAsyncIteration:
                    return
                yield chunk
        except ResourceNotFoundError as exc:
            raise ObjectStorageNotFoundError(_NOT_FOUND_MESSAGE) from exc
        except AzureError as exc:
            raise ObjectStorageError(_STORAGE_FAILURE_MESSAGE) from exc

    async def delete_object(self, *, storage_key: str) -> None:
        """Delete an object, succeeding when it is already absent."""
        try:
            await self._container_client.delete_blob(storage_key)
        except ResourceNotFoundError:
            return
        except AzureError as exc:
            raise ObjectStorageError(_STORAGE_FAILURE_MESSAGE) from exc

    async def get_object_properties(
        self,
        *,
        storage_key: str,
    ) -> StoredObjectProperties:
        """Read current Blob identity, size, and application metadata."""
        try:
            blob_client = self._container_client.get_blob_client(storage_key)
            properties = await _await_provider_operation(
                blob_client.get_blob_properties()
            )
            return StoredObjectProperties(
                entity_tag=normalize_azure_entity_tag(properties.etag),
                size_bytes=properties.size,
                metadata=properties.metadata,
            )
        except ResourceNotFoundError as exc:
            raise ObjectStorageNotFoundError(_NOT_FOUND_MESSAGE) from exc
        except AzureError as exc:
            raise ObjectStorageError(_STORAGE_FAILURE_MESSAGE) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise ObjectStorageError(_STORAGE_FAILURE_MESSAGE) from exc


def normalize_azure_entity_tag(value: object) -> str:
    """Normalize the quoted strong ETag shape returned by Azure Blob SDK."""
    if not isinstance(value, str) or not value:
        raise ValueError("entity tag is invalid")

    if len(value) >= 2 and value[0] == value[-1] == '"':
        normalized = value[1:-1]
        if not normalized:
            raise ValueError("entity tag is invalid")
        return normalized
    return value


__all__ = ["AzureBlobObjectStorage", "normalize_azure_entity_tag"]
