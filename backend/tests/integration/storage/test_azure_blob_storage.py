from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from azure.storage.blob.aio import ContainerClient
from tests.integration.helpers import byte_stream, with_isolated_storage

from nexus.files.ports import (
    ObjectStorageAlreadyExistsError,
    ObjectStorageNotFoundError,
)
from nexus.infrastructure.storage import AzureBlobObjectStorage


async def empty_stream() -> AsyncIterator[bytes]:
    if False:  # pragma: no cover - makes this an empty async generator
        yield b""


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


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

    asyncio.run(with_isolated_storage(scenario))


def test_zero_byte_object_round_trip() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        await storage.create_object(storage_key="empty", content=empty_stream())

        assert await collect(storage.stream_object(storage_key="empty")) == b""

    asyncio.run(with_isolated_storage(scenario))


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

    asyncio.run(with_isolated_storage(scenario))


def test_missing_download_fails_during_iteration() -> None:
    async def scenario(
        storage: AzureBlobObjectStorage,
        _: ContainerClient,
    ) -> None:
        stream = storage.stream_object(storage_key="missing")

        with pytest.raises(ObjectStorageNotFoundError):
            await collect(stream)

    asyncio.run(with_isolated_storage(scenario))


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

    asyncio.run(with_isolated_storage(scenario))


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

    asyncio.run(with_isolated_storage(scenario))


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

    asyncio.run(with_isolated_storage(scenario))


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

    asyncio.run(with_isolated_storage(scenario))


def test_conditional_multichunk_read_matches_admitted_etag():
    async def scenario(storage, client):
        await storage.create_object(
            storage_key="exact", content=byte_stream(b"0123456789abcdef")
        )
        properties = await storage.get_object_properties(storage_key="exact")
        chunks = [
            chunk
            async for chunk in storage.stream_object(
                storage_key="exact", expected_entity_tag=properties.entity_tag
            )
        ]
        assert b"".join(chunks) == b"0123456789abcdef"
        assert max(map(len, chunks)) <= 4

    asyncio.run(with_isolated_storage(scenario))


def test_replacement_between_properties_and_download_is_rejected():
    from nexus.files.ports import ObjectStorageError, ObjectStorageFailure

    async def scenario(storage, client):
        await storage.create_object(
            storage_key="exact", content=byte_stream(b"old-source")
        )
        properties = await storage.get_object_properties(storage_key="exact")
        await client.upload_blob(name="exact", data=b"new-source", overwrite=True)
        with pytest.raises(ObjectStorageError) as caught:
            await collect(
                storage.stream_object(
                    storage_key="exact", expected_entity_tag=properties.entity_tag
                )
            )
        assert caught.value.reason == ObjectStorageFailure.CHANGED

    asyncio.run(with_isolated_storage(scenario))


def test_replacement_during_multichunk_download_is_rejected():
    from nexus.files.ports import ObjectStorageError, ObjectStorageFailure

    async def scenario(storage, client):
        await storage.create_object(
            storage_key="exact", content=byte_stream(b"0123456789abcdef")
        )
        properties = await storage.get_object_properties(storage_key="exact")
        stream = storage.stream_object(
            storage_key="exact", expected_entity_tag=properties.entity_tag
        )
        try:
            assert await anext(stream) == b"0123"
            await client.upload_blob(
                name="exact", data=b"changed-contents!", overwrite=True
            )
            with pytest.raises(ObjectStorageError) as caught:
                await anext(stream)
            assert caught.value.reason == ObjectStorageFailure.CHANGED
        finally:
            await stream.aclose()

    asyncio.run(with_isolated_storage(scenario))


def test_normalized_artifact_create_and_verified_duplicate_round_trip() -> None:
    import hashlib

    from nexus.documents.application.normalize_document import NormalizeDocument
    from nexus.documents.application.write_normalized_artifact import (
        WriteNormalizedArtifact,
        canonical_artifact_chunks,
    )
    from nexus.documents.domain.extracted_document import (
        ExtractedBlock,
        ExtractedBlockKind,
        ExtractedDocument,
    )

    async def scenario(storage: AzureBlobObjectStorage, _: ContainerClient) -> None:
        document = NormalizeDocument().execute(
            ExtractedDocument(
                uuid.UUID(int=1),
                "source-etag",
                "nexus.txt",
                "1",
                (ExtractedBlock(0, ExtractedBlockKind.TEXT, "Cafe\u0301 Ω", 1, 2),),
            )
        )
        writer = WriteNormalizedArtifact(storage)
        reference = await writer.execute(
            document, organization_public_id=uuid.UUID(int=2)
        )
        assert (
            await writer.execute(document, organization_public_id=uuid.UUID(int=2))
            == reference
        )
        body = await collect(storage.stream_object(storage_key=reference.storage_key))
        assert body == b"".join(canonical_artifact_chunks(document))
        assert hashlib.sha256(body).hexdigest() == reference.checksum_sha256
        assert len(body) == reference.size_bytes

    asyncio.run(with_isolated_storage(scenario))
