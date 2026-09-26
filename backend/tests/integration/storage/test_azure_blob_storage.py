from __future__ import annotations

import asyncio
import os
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from urllib.parse import urlparse

import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import ContainerClient

from nexus.files.ports import (
    ObjectStorageAlreadyExistsError,
    ObjectStorageNotFoundError,
)
from nexus.infrastructure.storage import AzureBlobObjectStorage

_DEFAULT_AZURITE_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)


async def byte_stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def empty_stream() -> AsyncIterator[bytes]:
    if False:  # pragma: no cover - makes this an empty async generator
        yield b""


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


def _azurite_connection_string() -> str:
    return os.environ.get(
        "NEXUS_TEST_AZURITE_CONNECTION_STRING",
        _DEFAULT_AZURITE_CONNECTION_STRING,
    )


def _azurite_endpoint(connection_string: str) -> tuple[str, int]:
    endpoint = next(
        value.split("=", 1)[1]
        for value in connection_string.split(";")
        if value.startswith("BlobEndpoint=")
    )
    parsed = urlparse(endpoint)
    if parsed.hostname is None:
        raise ValueError("Azurite BlobEndpoint must contain a hostname")
    return parsed.hostname, parsed.port or 10000


def _require_azurite(connection_string: str) -> None:
    host, port = _azurite_endpoint(connection_string)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except OSError as exc:
        if os.environ.get("NEXUS_REQUIRE_AZURITE_TESTS") == "true":
            pytest.fail(f"Azurite is required but unavailable at {host}:{port}: {exc}")
        pytest.skip("Azurite is not available for object storage integration tests")


async def _with_isolated_storage(
    scenario: Callable[
        [AzureBlobObjectStorage, ContainerClient],
        Awaitable[None],
    ],
) -> None:
    connection_string = _azurite_connection_string()
    _require_azurite(connection_string)
    container_name = f"nexus-{uuid.uuid4().hex}"
    client = ContainerClient.from_connection_string(
        connection_string,
        container_name=container_name,
        max_single_get_size=4,
        max_chunk_get_size=4,
    )
    try:
        await client.create_container()
        await scenario(AzureBlobObjectStorage(client), client)
    finally:
        with suppress(ResourceNotFoundError):
            await client.delete_container()
        await client.close()


def test_multichunk_round_trip_preserves_exact_byte_order() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(
            storage_key="multi-chunk",
            content=byte_stream(b"alpha", b"-", b"beta", b"-", b"omega"),
        )

        assert (
            await collect(storage.stream_object(storage_key="multi-chunk"))
            == b"alpha-beta-omega"
        )

    asyncio.run(_with_isolated_storage(scenario))


def test_zero_byte_object_round_trip() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(storage_key="empty", content=empty_stream())

        assert await collect(storage.stream_object(storage_key="empty")) == b""

    asyncio.run(_with_isolated_storage(scenario))


def test_duplicate_create_preserves_original_bytes() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(
            storage_key="immutable",
            content=byte_stream(b"original"),
        )

        with pytest.raises(ObjectStorageAlreadyExistsError):
            await storage.create_object(
                storage_key="immutable",
                content=byte_stream(b"replacement"),
            )

        assert (
            await collect(storage.stream_object(storage_key="immutable")) == b"original"
        )

    asyncio.run(_with_isolated_storage(scenario))


def test_missing_download_fails_during_iteration() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        stream = storage.stream_object(storage_key="missing")

        with pytest.raises(ObjectStorageNotFoundError):
            await collect(stream)

    asyncio.run(_with_isolated_storage(scenario))


def test_delete_existing_object_and_missing_delete_are_idempotent() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(
            storage_key="delete-me",
            content=byte_stream(b"content"),
        )

        await storage.delete_object(storage_key="delete-me")
        await storage.delete_object(storage_key="delete-me")

        with pytest.raises(ObjectStorageNotFoundError):
            await collect(storage.stream_object(storage_key="delete-me"))

    asyncio.run(_with_isolated_storage(scenario))


def test_early_stream_close_leaves_shared_client_usable() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(
            storage_key="first",
            content=byte_stream(b"0123456789"),
        )
        stream = storage.stream_object(storage_key="first")

        assert await anext(stream)
        await stream.aclose()

        await storage.create_object(
            storage_key="second",
            content=byte_stream(b"still-usable"),
        )
        assert (
            await collect(storage.stream_object(storage_key="second"))
            == b"still-usable"
        )

    asyncio.run(_with_isolated_storage(scenario))


def test_normal_completion_leaves_shared_client_usable() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(
            storage_key="first",
            content=byte_stream(b"first"),
        )
        assert await collect(storage.stream_object(storage_key="first")) == b"first"

        await storage.create_object(
            storage_key="second",
            content=byte_stream(b"second"),
        )
        assert await collect(storage.stream_object(storage_key="second")) == b"second"

    asyncio.run(_with_isolated_storage(scenario))


def test_upload_context_metadata_round_trips_through_object_properties() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        client: ContainerClient,
    ) -> None:
        storage_key = f"files/{uuid.uuid4().hex}"
        protected_context = "nuc1.primary.frontend-upload-context"
        await client.upload_blob(
            name=storage_key,
            data=b"uploaded-content",
            metadata={"nexus_upload_context": protected_context},
            overwrite=False,
        )

        properties = await storage.get_object_properties(storage_key=storage_key)

        assert properties.size_bytes == len(b"uploaded-content")
        assert properties.metadata["nexus_upload_context"] == protected_context
        assert properties.entity_tag

    asyncio.run(_with_isolated_storage(scenario))
