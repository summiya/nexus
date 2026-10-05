import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nexus.documents.application.open_source import OpenDocumentSource
from nexus.documents.domain import Document
from nexus.documents.ports.processing import DocumentProcessingRequested
from nexus.documents.ports.source import (
    DocumentSourceError,
    DocumentSourceFacts,
    DocumentSourceFailure,
)
from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import (
    ObjectStorageError,
    ObjectStorageFailure,
    ObjectStorageNotFoundError,
    StoredObjectProperties,
)


class Storage:
    def __init__(self, chunks=None):
        self.properties = StoredObjectProperties(
            entity_tag="admitted-version", size_bytes=8, metadata={}
        )
        self.chunks = [b"abcd", b"efgh"] if chunks is None else chunks
        self.reads = 0
        self.closed = 0
        self.stream_calls = []
        self.properties_error = None
        self.stream_error = None
        self.properties_calls = 0

    async def get_object_properties(self, *, storage_key):
        self.properties_calls += 1
        if self.properties_error:
            raise self.properties_error
        return self.properties

    def stream_object(self, **kwargs):
        self.stream_calls.append(kwargs)
        return self._stream()

    async def _stream(self):
        try:
            for chunk in self.chunks:
                self.reads += 1
                yield chunk
            if self.stream_error:
                raise self.stream_error
        finally:
            self.closed += 1


def setup(*, chunks=None, limit=16):
    at = datetime.now(UTC)
    document = Document(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        source_file_public_id=uuid4(),
        created_at=at,
    ).start_processing(at=at, processing_version="test")
    request = DocumentProcessingRequested(
        uuid4(), document.organization_public_id, document.public_id
    )
    file = File(
        public_id=document.source_file_public_id,
        organization_public_id=document.organization_public_id,
        created_by_user_public_id=uuid4(),
        original_name="source.pdf",
        mime_type="application/pdf",
        size_bytes=8,
        storage_key=f"files/{uuid4().hex}",
        storage_status=FileStorageStatus.AVAILABLE,
        checksum_sha256=None,
        created_at=at,
        updated_at=at,
    )
    requests, files = AsyncMock(), AsyncMock()
    requests.get_source_facts.return_value = DocumentSourceFacts(
        file.public_id, "admitted-version", 8
    )
    files.get_file.return_value = file
    storage = Storage(chunks)
    capability = OpenDocumentSource(
        requests=requests, files=files, storage=storage, max_size_bytes=limit
    )
    return capability, document, request, requests, files, storage


def test_exact_source_is_lazy_ordered_and_preserves_metadata():
    async def run():
        capability, document, request, _requests, files, storage = setup()
        async with capability.open(document=document, request=request) as source:
            assert storage.stream_calls == []
            assert (
                source.entity_tag == "admitted-version"
                and source.expected_size_bytes == 8
            )
            assert source.source_file_public_id == document.source_file_public_id
            assert source.original_name == "source.pdf"
            assert source.mime_type == "application/pdf"
            assert await anext(source.content) == b"abcd"
            assert storage.reads == 1
            assert [chunk async for chunk in source.content] == [b"efgh"]
        files.get_file.assert_awaited_once_with(
            organization_public_id=document.organization_public_id,
            file_public_id=document.source_file_public_id,
        )
        assert storage.stream_calls == [
            {
                "storage_key": files.get_file.return_value.storage_key,
                "expected_entity_tag": "admitted-version",
            }
        ]
        assert storage.closed == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "scenario,reason",
    [
        ("tenant", "invalid_request"),
        ("document", "invalid_request"),
        ("queued", "invalid_request"),
        ("request_missing", "invalid_request"),
        ("wrong_source", "invalid_request"),
        ("file_missing", "unavailable"),
        ("file_pending", "unavailable"),
        ("file_foreign", "invalid_request"),
        ("file_size", "changed"),
        ("oversize", "too_large"),
        ("etag", "changed"),
        ("object_size", "changed"),
    ],
)
def test_preflight_fails_without_download(scenario, reason):
    async def run():
        capability, document, request, requests, files, storage = setup(
            limit=4 if scenario == "oversize" else 16
        )
        if scenario == "tenant":
            request = replace(request, organization_public_id=uuid4())
        if scenario == "document":
            request = replace(request, document_public_id=uuid4())
        if scenario == "queued":
            document = Document(
                public_id=document.public_id,
                organization_public_id=document.organization_public_id,
                source_file_public_id=document.source_file_public_id,
                created_at=document.created_at,
            )
        if scenario == "request_missing":
            requests.get_source_facts.return_value = None
        if scenario == "wrong_source":
            requests.get_source_facts.return_value = DocumentSourceFacts(
                uuid4(), "admitted-version", 8
            )
        if scenario == "file_missing":
            files.get_file.return_value = None
        if scenario == "file_pending":
            files.get_file.return_value = replace(
                files.get_file.return_value, storage_status=FileStorageStatus.PENDING
            )
        if scenario == "file_foreign":
            files.get_file.return_value = replace(
                files.get_file.return_value, organization_public_id=uuid4()
            )
        if scenario == "file_size":
            files.get_file.return_value = replace(
                files.get_file.return_value, size_bytes=9
            )
        if scenario == "etag":
            storage.properties = StoredObjectProperties(
                entity_tag="changed", size_bytes=8, metadata={}
            )
        if scenario == "object_size":
            storage.properties = StoredObjectProperties(
                entity_tag="admitted-version", size_bytes=9, metadata={}
            )
        with pytest.raises(DocumentSourceError) as caught:
            async with capability.open(document=document, request=request):
                pytest.fail("Invalid source admitted")
        assert caught.value.reason == reason
        assert storage.stream_calls == []
        if scenario not in {"etag", "object_size"}:
            assert storage.properties_calls == 0

    asyncio.run(run())


@pytest.mark.parametrize("chunks", [[b"abcd", b"excess"], [b"abcd"], ["invalid"]])
def test_stream_detects_overflow_truncation_and_invalid_chunks(chunks):
    async def run():
        capability, document, request, _, _, storage = setup(chunks=chunks)
        yielded = []
        with pytest.raises(DocumentSourceError) as caught:
            async with capability.open(document=document, request=request) as source:
                async for chunk in source.content:
                    yielded.append(chunk)
        assert caught.value.reason == (
            DocumentSourceFailure.STORAGE_FAILURE
            if chunks == ["invalid"]
            else DocumentSourceFailure.CHANGED
        )
        assert yielded == ([] if chunks == ["invalid"] else [b"abcd"])
        assert storage.closed == 1

    asyncio.run(run())


@pytest.mark.parametrize("where", ["properties", "stream"])
@pytest.mark.parametrize(
    "error,reason",
    [
        (ObjectStorageNotFoundError("private"), "unavailable"),
        (ObjectStorageError("private", reason=ObjectStorageFailure.CHANGED), "changed"),
        (
            ObjectStorageError("private", reason=ObjectStorageFailure.TRANSIENT),
            "transient_storage",
        ),
        (
            ObjectStorageError("private", reason=ObjectStorageFailure.ACCESS),
            "storage_access",
        ),
        (ObjectStorageError("private"), "storage_failure"),
    ],
)
def test_safe_storage_classification(where, error, reason):
    async def run():
        capability, document, request, _, _, storage = setup()
        setattr(storage, f"{where}_error", error)
        with pytest.raises(DocumentSourceError) as caught:
            async with capability.open(document=document, request=request) as source:
                async for _ in source.content:
                    pass
        assert caught.value.reason == reason
        assert str(caught.value) == "Document source access failed"
        assert caught.value.__cause__ is error

    asyncio.run(run())


@pytest.mark.parametrize("exit_kind", ["break", "failure", "cancel", "unused"])
def test_context_closes_on_early_exit_without_draining(exit_kind):
    async def run():
        capability, document, request, _, _, storage = setup()
        entered = asyncio.Event()

        async def consume():
            async with capability.open(document=document, request=request) as source:
                if exit_kind == "unused":
                    return
                assert await anext(source.content) == b"abcd"
                entered.set()
                if exit_kind == "failure":
                    raise RuntimeError("downstream")
                if exit_kind == "cancel":
                    await asyncio.Event().wait()

        task = asyncio.create_task(consume())
        if exit_kind == "cancel":
            await entered.wait()
            task.cancel()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        if exit_kind == "cancel":
            assert isinstance(result, asyncio.CancelledError)
        if exit_kind == "failure":
            assert isinstance(result, RuntimeError)
        assert storage.reads == (0 if exit_kind == "unused" else 1)
        assert storage.closed == (0 if exit_kind == "unused" else 1)

    asyncio.run(run())


def test_zero_byte_source_and_exact_limit_are_supported():
    async def run():
        for size, chunks in [(0, []), (8, [b"abcd", b"efgh"])]:
            capability, document, request, requests, files, storage = setup(
                chunks=chunks, limit=8
            )
            requests.get_source_facts.return_value = DocumentSourceFacts(
                document.source_file_public_id, "admitted-version", size
            )
            files.get_file.return_value = replace(
                files.get_file.return_value, size_bytes=size
            )
            storage.properties = StoredObjectProperties(
                entity_tag="admitted-version", size_bytes=size, metadata={}
            )
            async with capability.open(document=document, request=request) as source:
                assert sum([len(chunk) async for chunk in source.content]) == size

    asyncio.run(run())


def test_large_stream_has_bounded_memory_and_backpressure():
    import tracemalloc

    async def run():
        chunk_size, chunk_count = 8192, 2048
        size = chunk_size * chunk_count
        capability, document, request, requests, files, storage = setup(limit=size)
        requests.get_source_facts.return_value = DocumentSourceFacts(
            document.source_file_public_id, "admitted-version", size
        )
        files.get_file.return_value = replace(
            files.get_file.return_value, size_bytes=size
        )
        storage.properties = StoredObjectProperties(
            entity_tag="admitted-version", size_bytes=size, metadata={}
        )
        produced = 0

        async def content(**kwargs):
            nonlocal produced
            for i in range(chunk_count):
                produced += 1
                yield bytes([i % 256]) * chunk_size

        storage.stream_object = content
        tracemalloc.start()
        try:
            consumed = 0
            async with capability.open(document=document, request=request) as source:
                async for chunk in source.content:
                    consumed += 1
                    assert len(chunk) == chunk_size
                    assert produced == consumed
            assert consumed == chunk_count
            assert tracemalloc.get_traced_memory()[1] < 1024 * 1024
        finally:
            tracemalloc.stop()

    asyncio.run(run())


def test_independent_documents_can_stream_concurrently():
    async def run():
        entered, release = asyncio.Queue(), asyncio.Event()

        async def content(**kwargs):
            await entered.put(kwargs["storage_key"])
            await release.wait()
            yield b"abcdefgh"

        async def consume():
            capability, document, request, _, _, storage = setup()
            storage.stream_object = content
            async with capability.open(document=document, request=request) as source:
                async for _ in source.content:
                    pass

        tasks = [asyncio.create_task(consume()) for _ in range(2)]
        try:
            keys = [await asyncio.wait_for(entered.get(), timeout=2) for _ in range(2)]
            assert len(set(keys)) == 2
        finally:
            release.set()
            await asyncio.gather(*tasks)

    asyncio.run(run())


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_file_size_bound_must_be_a_positive_integer(limit):
    with pytest.raises(ValueError):
        setup(limit=limit)
