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
)

_ALREADY_EXISTS_MESSAGE = "The object already exists in storage."
_NOT_FOUND_MESSAGE = "The object was not found in storage."
_STORAGE_FAILURE_MESSAGE = "The object storage operation failed."


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
        try:
            await self._container_client.upload_blob(
                name=storage_key,
                data=content,
                blob_type=BlobType.BLOCKBLOB,
                overwrite=False,
            )
        except ResourceExistsError as exc:
            raise ObjectStorageAlreadyExistsError(_ALREADY_EXISTS_MESSAGE) from exc
        except AzureError as exc:
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
