import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from tests.unit.documents.test_open_source import setup

from nexus.documents.application.extract_document import ExtractDocument
from nexus.documents.domain import (
    DocumentStatus,
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionFailure as Failure,
)
from nexus.documents.ports.source import DocumentSourceError, DocumentSourceFailure
from nexus.infrastructure.extraction.text import (
    MarkdownDocumentExtractor,
    TxtDocumentExtractor,
)


def capability(
    data=b"# Heading", *, name="source.md", mime="text/markdown", chunks=None
):
    opener, document, request, requests, files, storage = setup(
        chunks=[data] if chunks is None else chunks
    )
    files.get_file.return_value = replace(
        files.get_file.return_value,
        original_name=name,
        mime_type=mime,
        size_bytes=len(data),
    )
    requests.get_source_facts.return_value = replace(
        requests.get_source_facts.return_value, expected_size_bytes=len(data)
    )
    storage.properties = replace(storage.properties, size_bytes=len(data))
    return (
        ExtractDocument(
            source=opener,
            txt=TxtDocumentExtractor(),
            markdown=MarkdownDocumentExtractor(),
        ),
        document,
        request,
        storage,
    )


@pytest.mark.parametrize(
    "name,mime,extractor",
    [
        ("a.TXT", "TEXT/PLAIN", "nexus.txt"),
        ("a.txt", "application/octet-stream", "nexus.txt"),
        ("a.MD", "text/plain", "nexus.commonmark"),
        ("a.md", "text/markdown", "nexus.commonmark"),
        ("a.md", "application/octet-stream", "nexus.commonmark"),
    ],
)
def test_selection_reuses_admission_rules_and_source_closes_after_success(
    name, mime, extractor
):
    async def run():
        app, document, request, storage = capability(name=name, mime=mime)
        result = await app.execute(document=document, request=request)
        assert result.extractor_id == extractor
        assert result.source_file_public_id == document.source_file_public_id
        assert result.source_entity_tag == "admitted-version"
        assert storage.closed == 1
        assert document.status is DocumentStatus.PROCESSING
        assert document.extractor_version is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,mime",
    [
        ("a.pdf", "application/pdf"),
        ("a.txt", "text/markdown"),
        ("a.md", "application/pdf"),
        ("a.rst", "text/plain"),
        ("a", "text/plain"),
    ],
)
def test_unsupported_selection_never_reads_source(name, mime):
    async def run():
        app, document, request, storage = capability(name=name, mime=mime)
        with pytest.raises(DocumentExtractionError) as exc:
            await app.execute(document=document, request=request)
        assert exc.value.reason is Failure.UNSUPPORTED
        assert storage.reads == 0

    asyncio.run(run())


@pytest.mark.parametrize("name", ["a.txt", "a.md"])
@pytest.mark.parametrize("chunks", [[b"short"], [b"too many bytes"], [b"# Heading"]])
def test_no_output_escapes_a_failed_exact_source(name, chunks):
    async def run():
        app, document, request, storage = capability(
            name=name, mime="text/plain", chunks=chunks
        )
        if chunks == [b"# Heading"]:
            storage.stream_error = DocumentSourceError(
                DocumentSourceFailure.TRANSIENT_STORAGE
            )
        with pytest.raises(DocumentSourceError):
            await app.execute(document=document, request=request)
        assert storage.closed == 1

    asyncio.run(run())


def test_invalid_tenant_fails_before_storage_or_extraction():
    async def run():
        app, document, request, storage = capability()
        foreign = replace(request, organization_public_id=uuid4())
        with pytest.raises(DocumentSourceError) as exc:
            await app.execute(document=document, request=foreign)
        assert exc.value.reason is DocumentSourceFailure.INVALID_REQUEST
        assert storage.properties_calls == 0 and storage.reads == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "data,reason", [(b"\x00", Failure.MALFORMED), (b"  ", Failure.EMPTY)]
)
def test_extraction_errors_close_source(data, reason):
    async def run():
        app, document, request, storage = capability(data)
        with pytest.raises(DocumentExtractionError) as exc:
            await app.execute(document=document, request=request)
        assert exc.value.reason is reason
        assert storage.closed == 1

    asyncio.run(run())


def test_cancellation_while_reading_closes_source():
    async def run():
        app, document, request, storage = capability()
        reading = asyncio.Event()
        closed = asyncio.Event()

        async def blocked(**kwargs):
            try:
                reading.set()
                await asyncio.Future()
                yield b"unused"
            finally:
                closed.set()

        storage.stream_object = blocked
        task = asyncio.create_task(app.execute(document=document, request=request))
        await reading.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()

    asyncio.run(run())


def test_extractors_are_swappable_without_infrastructure_types():
    async def run():
        opener, document, request, _, files, storage = setup()
        files.get_file.return_value = replace(
            files.get_file.return_value,
            original_name="source.txt",
            mime_type="text/plain",
        )
        expected = ExtractedDocument(
            document.source_file_public_id,
            "admitted-version",
            "test.txt",
            "1",
            (ExtractedBlock(0, ExtractedBlockKind.TEXT, "abcdefgh", 1, 2),),
        )

        async def read(source):
            assert b"".join([chunk async for chunk in source.content]) == b"abcdefgh"
            return expected

        fake = AsyncMock()
        fake.extract.side_effect = read
        other = AsyncMock()
        app = ExtractDocument(source=opener, txt=fake, markdown=other)
        assert await app.execute(document=document, request=request) == expected
        fake.extract.assert_awaited_once()
        other.extract.assert_not_called()
        assert storage.closed == 1

    asyncio.run(run())
