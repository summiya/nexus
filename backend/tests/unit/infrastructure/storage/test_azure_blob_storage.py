from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobType
from azure.storage.blob.aio import ContainerClient

from nexus.files.ports import (
    ObjectStorageAlreadyExistsError,
    ObjectStorageError,
    ObjectStorageNotFoundError,
)
from nexus.infrastructure.storage import AzureBlobObjectStorage


async def byte_stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


class FakeDownloader:
    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks

    def chunks(self) -> AsyncIterator[bytes]:
        return self._chunks


class FakeContainerClient:
    def __init__(self) -> None:
        self.upload_calls: list[dict[str, object]] = []
        self.uploaded_chunks: list[bytes] = []
        self.download_calls: list[str] = []
        self.download_options: list[dict[str, object]] = []
        self.delete_calls: list[str] = []
        self.properties_calls: list[str] = []
        self.upload_error: BaseException | None = None
        self.upload_failure_wrapper: AzureError | None = None
        self.download_error: BaseException | None = None
        self.delete_error: BaseException | None = None
        self.properties_error: BaseException | None = None
        self.properties = SimpleNamespace(
            etag='"0x8D123"',
            size=42,
            metadata={"nexus_upload_context": "protected"},
        )
        self.consume_upload = False
        self.download_chunks: AsyncIterator[bytes] = byte_stream(b"content")
        self.close_calls = 0

    async def upload_blob(
        self,
        *,
        name: str,
        data: AsyncIterable[bytes],
        blob_type: BlobType,
        overwrite: bool,
    ) -> None:
        self.upload_calls.append(
            {
                "name": name,
                "data": data,
                "blob_type": blob_type,
                "overwrite": overwrite,
            }
        )
        if self.upload_error is not None:
            raise self.upload_error
        if self.consume_upload:
            try:
                async for chunk in data:
                    self.uploaded_chunks.append(chunk)
            except BaseException as exc:
                if self.upload_failure_wrapper is not None:
                    raise self.upload_failure_wrapper from exc
                raise

    async def download_blob(self, blob: str, **kwargs: object) -> FakeDownloader:
        self.download_calls.append(blob)
        self.download_options.append(kwargs)
        if self.download_error is not None:
            raise self.download_error
        return FakeDownloader(self.download_chunks)

    async def delete_blob(self, blob: str) -> None:
        self.delete_calls.append(blob)
        if self.delete_error is not None:
            raise self.delete_error

    def get_blob_client(self, blob: str) -> FakeContainerClient:
        self.properties_calls.append(blob)
        return self

    async def get_blob_properties(self) -> object:
        if self.properties_error is not None:
            raise self.properties_error
        return self.properties

    async def close(self) -> None:
        self.close_calls += 1


def adapter_for(fake_client: FakeContainerClient) -> AzureBlobObjectStorage:
    return AzureBlobObjectStorage(cast(ContainerClient, fake_client))


async def collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in stream]


def test_create_streams_content_to_atomic_block_blob_upload() -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.consume_upload = True
        adapter = adapter_for(fake_client)
        content = byte_stream(b"first", b"second")

        await adapter.create_object(storage_key="opaque-key", content=content)

        assert len(fake_client.upload_calls) == 1
        assert fake_client.upload_calls[0]["name"] == "opaque-key"
        assert isinstance(fake_client.upload_calls[0]["data"], AsyncIterable)
        assert fake_client.upload_calls[0]["blob_type"] is BlobType.BLOCKBLOB
        assert fake_client.upload_calls[0]["overwrite"] is False
        assert fake_client.uploaded_chunks == [b"first", b"second"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (ResourceExistsError("provider detail"), ObjectStorageAlreadyExistsError),
        (AzureError("provider detail"), ObjectStorageError),
    ],
)
def test_create_translates_provider_errors_once(
    provider_error: AzureError,
    expected_error: type[ObjectStorageError],
) -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.upload_error = provider_error
        adapter = adapter_for(fake_client)

        with pytest.raises(expected_error) as captured:
            await adapter.create_object(
                storage_key="opaque-key",
                content=byte_stream(b"content"),
            )

        assert "provider detail" not in str(captured.value)
        assert captured.value.__cause__ is provider_error
        assert len(fake_client.upload_calls) == 1

    asyncio.run(scenario())


def test_create_does_not_translate_upload_producer_failure() -> None:
    class ProducerError(Exception):
        pass

    producer_error = ProducerError("producer failed")

    async def failing_content() -> AsyncIterator[bytes]:
        yield b"first"
        raise producer_error

    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.consume_upload = True
        adapter = adapter_for(fake_client)

        with pytest.raises(ProducerError) as captured:
            await adapter.create_object(
                storage_key="opaque-key",
                content=failing_content(),
            )

        assert captured.value is producer_error

    asyncio.run(scenario())


def test_create_does_not_translate_azure_error_from_upload_producer() -> None:
    producer_error = AzureError("producer failed")

    async def failing_content() -> AsyncIterator[bytes]:
        yield b"first"
        raise producer_error

    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.consume_upload = True
        fake_client.upload_failure_wrapper = AzureError("SDK upload failed")
        adapter = adapter_for(fake_client)

        with pytest.raises(AzureError) as captured:
            await adapter.create_object(
                storage_key="opaque-key",
                content=failing_content(),
            )

        assert captured.value is producer_error

    asyncio.run(scenario())


def test_stream_is_lazy_and_preserves_chunk_order() -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.download_chunks = byte_stream(b"one", b"two")
        adapter = adapter_for(fake_client)

        stream = adapter.stream_object(storage_key="opaque-key")

        assert fake_client.download_calls == []
        assert await collect(stream) == [b"one", b"two"]
        assert fake_client.download_calls == ["opaque-key"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (ResourceNotFoundError("provider detail"), ObjectStorageNotFoundError),
        (AzureError("provider detail"), ObjectStorageError),
    ],
)
def test_stream_translates_download_start_errors_during_consumption(
    provider_error: AzureError,
    expected_error: type[ObjectStorageError],
) -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.download_error = provider_error
        adapter = adapter_for(fake_client)
        stream = adapter.stream_object(storage_key="opaque-key")

        with pytest.raises(expected_error) as captured:
            await anext(stream)

        assert "provider detail" not in str(captured.value)
        assert captured.value.__cause__ is provider_error
        assert fake_client.download_calls == ["opaque-key"]

    asyncio.run(scenario())


def test_stream_translates_provider_failure_after_a_chunk() -> None:
    provider_error = AzureError("provider detail")

    async def failing_chunks() -> AsyncIterator[bytes]:
        yield b"first"
        raise provider_error

    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.download_chunks = failing_chunks()
        adapter = adapter_for(fake_client)
        stream = adapter.stream_object(storage_key="opaque-key")

        assert await anext(stream) == b"first"
        with pytest.raises(ObjectStorageError) as captured:
            await anext(stream)

        assert captured.value.__cause__ is provider_error

    asyncio.run(scenario())


def test_stream_cancellation_waits_for_provider_operation_then_propagates() -> None:
    class BlockingChunks:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.settled = False

        def __aiter__(self) -> BlockingChunks:
            return self

        async def __anext__(self) -> bytes:
            self.started.set()
            await self.release.wait()
            self.settled = True
            return b"content"

    async def scenario() -> None:
        chunks = BlockingChunks()
        fake_client = FakeContainerClient()
        fake_client.download_chunks = chunks
        adapter = adapter_for(fake_client)
        stream = adapter.stream_object(storage_key="opaque-key")
        consumer = asyncio.create_task(anext(stream))

        await chunks.started.wait()
        consumer.cancel()
        await asyncio.sleep(0)

        assert not consumer.done()
        assert not chunks.settled

        chunks.release.set()
        with pytest.raises(asyncio.CancelledError):
            await consumer

        assert chunks.settled
        assert fake_client.close_calls == 0

    asyncio.run(scenario())


def test_early_stream_close_leaves_borrowed_client_reusable() -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.download_chunks = byte_stream(b"first", b"second")
        adapter = adapter_for(fake_client)
        stream = adapter.stream_object(storage_key="first-key")

        assert await anext(stream) == b"first"
        await stream.aclose()

        fake_client.download_chunks = byte_stream(b"next")
        assert await collect(adapter.stream_object(storage_key="second-key")) == [
            b"next"
        ]
        assert fake_client.download_calls == ["first-key", "second-key"]
        assert fake_client.close_calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (ResourceNotFoundError("missing"), None),
        (AzureError("provider detail"), ObjectStorageError),
    ],
)
def test_delete_is_idempotent_and_translates_other_provider_errors(
    provider_error: AzureError,
    expected_error: type[ObjectStorageError] | None,
) -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.delete_error = provider_error
        adapter = adapter_for(fake_client)

        if expected_error is None:
            await adapter.delete_object(storage_key="opaque-key")
        else:
            with pytest.raises(expected_error) as captured:
                await adapter.delete_object(storage_key="opaque-key")
            assert "provider detail" not in str(captured.value)
            assert captured.value.__cause__ is provider_error

        assert fake_client.delete_calls == ["opaque-key"]
        assert fake_client.close_calls == 0

    asyncio.run(scenario())


def test_properties_normalize_only_expected_surrounding_etag_quotes() -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        adapter = adapter_for(fake_client)

        properties = await adapter.get_object_properties(storage_key="opaque-key")

        assert properties.entity_tag == "0x8D123"
        assert properties.size_bytes == 42
        assert properties.metadata == {"nexus_upload_context": "protected"}
        assert fake_client.properties_calls == ["opaque-key"]

        fake_client.properties.etag = 'W/"0xWEAK"'
        weak = await adapter.get_object_properties(storage_key="opaque-key")
        assert weak.entity_tag == 'W/"0xWEAK"'

    asyncio.run(scenario())


@pytest.mark.parametrize("malformed_etag", [None, "", 123, ["0x8D123"]])
def test_properties_reject_malformed_etags(malformed_etag: object) -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.properties.etag = malformed_etag
        adapter = adapter_for(fake_client)

        with pytest.raises(ObjectStorageError) as captured:
            await adapter.get_object_properties(storage_key="opaque-key")

        assert str(captured.value) == "The object storage operation failed."
        assert isinstance(captured.value.__cause__, (TypeError, ValueError))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (ResourceNotFoundError("missing"), ObjectStorageNotFoundError),
        (AzureError("provider detail"), ObjectStorageError),
    ],
)
def test_properties_translate_provider_errors(
    provider_error: AzureError,
    expected_error: type[ObjectStorageError],
) -> None:
    async def scenario() -> None:
        fake_client = FakeContainerClient()
        fake_client.properties_error = provider_error
        adapter = adapter_for(fake_client)

        with pytest.raises(expected_error) as captured:
            await adapter.get_object_properties(storage_key="opaque-key")

        assert "provider detail" not in str(captured.value)
        assert captured.value.__cause__ is provider_error

    asyncio.run(scenario())


def test_conditional_download_pins_etag_at_adapter_boundary() -> None:
    from azure.core import MatchConditions

    async def run():
        fake = FakeContainerClient()
        adapter = adapter_for(fake)
        for tag in ("0x8D123", '"0x8D123"'):
            fake.download_chunks = byte_stream(b"content")
            assert await collect(
                adapter.stream_object(storage_key="opaque-key", expected_entity_tag=tag)
            ) == [b"content"]
            assert fake.download_options[-1] == {
                "etag": '"0x8D123"',
                "match_condition": MatchConditions.IfNotModified,
                "max_concurrency": 1,
            }

    asyncio.run(run())


@pytest.mark.parametrize("tag", ["*", 'W/"weak"', "", "\r\ninjected", 'bad"etag'])
def test_unsafe_conditional_tags_fail_closed(tag):
    from nexus.files.ports import ObjectStorageFailure

    async def run():
        fake = FakeContainerClient()
        with pytest.raises(ObjectStorageError) as caught:
            await collect(
                adapter_for(fake).stream_object(
                    storage_key="opaque-key", expected_entity_tag=tag
                )
            )
        assert caught.value.reason == ObjectStorageFailure.CHANGED
        assert fake.download_calls == []

    asyncio.run(run())


@pytest.mark.parametrize("where", ["properties", "start", "chunks"])
@pytest.mark.parametrize(
    "kind", ["changed", "access", "transient", "connection", "timeout", "other"]
)
def test_download_failures_have_safe_provider_neutral_classification(where, kind):
    from azure.core.exceptions import HttpResponseError, ServiceRequestError

    from nexus.files.ports import ObjectStorageFailure

    if kind == "connection":
        error = ServiceRequestError("private provider detail")
    elif kind == "timeout":
        error = TimeoutError("private provider detail")
    elif kind == "other":
        error = AzureError("private provider detail")
    else:
        error = HttpResponseError("private provider detail")
        error.status_code = {"changed": 412, "access": 403, "transient": 503}[kind]

    async def run():
        fake = FakeContainerClient()
        if where == "properties":
            fake.properties_error = error
        if where == "start":
            fake.download_error = error
        if where == "chunks":

            async def chunks():
                yield b"first"
                raise error

            fake.download_chunks = chunks()
        adapter = adapter_for(fake)
        with pytest.raises(ObjectStorageError) as caught:
            if where == "properties":
                await adapter.get_object_properties(storage_key="opaque-key")
            else:
                await collect(
                    adapter.stream_object(
                        storage_key="opaque-key", expected_entity_tag="admitted-version"
                    )
                )
        expected = {
            "connection": "transient",
            "timeout": "transient",
            "other": "other",
        }.get(kind, kind)
        assert caught.value.reason == ObjectStorageFailure(expected)
        assert str(caught.value) == "The object storage operation failed."
        assert caught.value.__cause__ is error

    asyncio.run(run())


def test_early_close_closes_underlying_generator_without_draining():
    async def run():
        closed = False
        pulled = 0

        async def chunks():
            nonlocal closed, pulled
            try:
                for _ in range(5):
                    pulled += 1
                    yield b"chunk"
            finally:
                closed = True

        fake = FakeContainerClient()
        fake.download_chunks = chunks()
        stream = adapter_for(fake).stream_object(
            storage_key="opaque-key", expected_entity_tag="admitted-version"
        )
        assert await anext(stream) == b"chunk"
        await stream.aclose()
        assert closed and pulled == 1
        assert fake.close_calls == 0

    asyncio.run(run())


@pytest.mark.parametrize("where", ["start", "properties"])
@pytest.mark.parametrize("fails", [False, True])
def test_cancellation_settles_inflight_operation_and_remains_cancellation(where, fails):
    async def run():
        fake = FakeContainerClient()
        started, release = asyncio.Event(), asyncio.Event()
        settled = False

        async def block(*args, **kwargs):
            nonlocal settled
            started.set()
            await release.wait()
            settled = True
            if fails:
                raise AzureError("private provider failure during cancellation")
            return (
                FakeDownloader(byte_stream(b"content"))
                if where == "start"
                else fake.properties
            )

        if where == "start":
            fake.download_blob = block
        else:
            fake.get_blob_properties = block
        adapter = adapter_for(fake)
        stream = adapter.stream_object(
            storage_key="opaque-key", expected_entity_tag="admitted-version"
        )
        task = asyncio.create_task(
            anext(stream)
            if where == "start"
            else adapter.get_object_properties(storage_key="opaque-key")
        )
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not settled
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert settled and fake.close_calls == 0

    asyncio.run(run())


def test_create_cancellation_keeps_producer_alive_until_upload_settles():
    async def run():
        client = Mock()
        entered, release, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        produced = []

        async def content():
            yield b"first"
            await release.wait()
            yield b"last"

        async def upload(**kwargs):
            entered.set()
            async for chunk in kwargs["data"]:
                produced.append(chunk)
            settled.set()

        client.upload_blob = AsyncMock(side_effect=upload)
        storage = AzureBlobObjectStorage(client)
        task = asyncio.create_task(
            storage.create_object(storage_key="artifact", content=content())
        )
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert settled.is_set()
        assert produced == [b"first", b"last"]

    asyncio.run(run())
