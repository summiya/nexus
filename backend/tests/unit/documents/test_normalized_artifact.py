import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nexus.documents.application.normalize_document import (
    DocumentNormalizationError,
    NormalizeDocument,
)
from nexus.documents.application.normalize_document import (
    DocumentNormalizationFailure as Failure,
)
from nexus.documents.application.write_normalized_artifact import (
    WriteNormalizedArtifact,
    canonical_artifact_chunks,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedDocument,
    ExtractedListItem,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind as Kind,
)
from nexus.files.ports.storage import (
    ObjectStorageAlreadyExistsError,
    ObjectStorageError,
    ObjectStorageFailure,
    StoredObjectProperties,
)


def normalized(text="Café Ω"):
    return NormalizeDocument().execute(
        ExtractedDocument(
            UUID(int=1),
            "verified-etag",
            "nexus.txt",
            "1",
            (ExtractedBlock(0, Kind.TEXT, text, 1, 2),),
        )
    )


class Storage:
    def __init__(self):
        self.objects = {}
        self.creates = []
        self.pins = []
        self.closed = 0
        self.failure = None
        self.read_failure = None
        self.read_override = None
        self.commit_then_wait = False
        self.started = asyncio.Event()

    async def create_object(self, *, storage_key, content):
        self.creates.append(storage_key)
        if self.failure is not None:
            raise self.failure
        body = b"".join([chunk async for chunk in content])
        await asyncio.sleep(0)
        if storage_key in self.objects:
            raise ObjectStorageAlreadyExistsError()
        self.objects[storage_key] = body
        if self.commit_then_wait:
            self.started.set()
            await asyncio.Event().wait()

    async def get_object_properties(self, *, storage_key):
        return StoredObjectProperties(
            "artifact-etag", len(self.objects[storage_key]), {}
        )

    async def stream_object(self, *, storage_key, expected_entity_tag=None):
        self.pins.append((storage_key, expected_entity_tag))
        try:
            if self.read_failure is not None:
                raise self.read_failure
            body = (
                self.objects[storage_key]
                if self.read_override is None
                else self.read_override
            )
            for offset in range(0, len(body), 17):
                yield body[offset : offset + 17]
        finally:
            self.closed += 1


def test_canonical_json_is_explicit_sorted_utf8_and_deterministic():
    document = normalized()
    body = b"".join(canonical_artifact_chunks(document))
    expected = {
        "schema_version": 1,
        "source_file_public_id": str(UUID(int=1)),
        "source_entity_tag": "verified-etag",
        "extractor_id": "nexus.txt",
        "extractor_version": "1",
        "normalizer_id": "nexus.normalization",
        "normalizer_version": "1",
        "page_count": None,
        "blocks": [
            {
                "source_block_index": 0,
                "kind": "text",
                "text": "Café Ω",
                "start_line": 1,
                "end_line": 2,
                "page_number": None,
                "heading_level": None,
                "list_item": None,
                "quote_depth": 0,
                "section_path": [],
            }
        ],
    }
    assert body == json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert body == b"".join(canonical_artifact_chunks(document))
    assert b"Caf\xc3\xa9 \xce\xa9" in body


def test_chunked_string_escaping_matches_canonical_json_without_large_chunks():
    document = normalized("x" * 8191 + '"\\\n\x01Ω' * 2000)
    chunks = list(canonical_artifact_chunks(document))
    body = b"".join(chunks)
    assert max(map(len, chunks)) <= 8192 * 6 + 2
    assert (
        body
        == json.dumps(
            json.loads(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    assert json.loads(body)["blocks"][0]["text"] == document.blocks[0].text


def test_serialization_preserves_structural_metadata_and_page_count():
    source = ExtractedDocument(
        UUID(int=1),
        "etag",
        "nexus.commonmark",
        "1",
        (
            ExtractedBlock(0, Kind.HEADING, "H1", 1, 2, 1),
            ExtractedBlock(
                1,
                Kind.PARAGRAPH,
                "item",
                2,
                3,
                list_item=ExtractedListItem(2, 2, 1, True, 0),
                quote_depth=2,
            ),
        ),
    )
    data = json.loads(
        b"".join(canonical_artifact_chunks(NormalizeDocument().execute(source)))
    )
    assert data["blocks"][1]["section_path"] == [0]
    assert data["blocks"][1]["quote_depth"] == 2
    assert data["blocks"][1]["list_item"] == {
        "list_start_line": 2,
        "item_start_line": 2,
        "depth": 1,
        "ordered": True,
        "ordinal": 0,
    }
    pdf = ExtractedDocument(
        UUID(int=1),
        "etag",
        "nexus.pdf-ocr",
        "1",
        (ExtractedBlock(0, Kind.TEXT, "OCR", page_number=3),),
        5,
    )
    data = json.loads(
        b"".join(canonical_artifact_chunks(NormalizeDocument().execute(pdf)))
    )
    assert data["page_count"] == 5
    assert data["blocks"][0]["page_number"] == 3
    assert data["blocks"][0]["start_line"] is None


def test_success_checksum_key_reference_and_exact_duplicate():
    async def run():
        storage = Storage()
        writer = WriteNormalizedArtifact(storage)
        document = normalized()
        result = await writer.execute(document, organization_public_id=UUID(int=2))
        body = storage.objects[result.storage_key]
        assert result.checksum_sha256 == hashlib.sha256(body).hexdigest()
        assert result.size_bytes == len(body)
        assert (
            result.storage_key
            == f"documents/{UUID(int=2)}/{UUID(int=1)}/normalized/v1/{result.checksum_sha256}.json"
        )
        assert result.source_entity_tag == document.source_entity_tag
        assert result.normalizer_version == result.extractor_version == "1"
        assert result.schema_version == 1
        assert (
            await writer.execute(document, organization_public_id=UUID(int=2)) == result
        )
        assert storage.pins == [(result.storage_key, "artifact-etag")]
        assert storage.closed == 1
        assert "Café" not in repr(result)
        with pytest.raises(FrozenInstanceError):
            result.size_bytes = 0
        other = await writer.execute(document, organization_public_id=UUID(int=3))
        assert other.storage_key != result.storage_key
        assert other.checksum_sha256 == result.checksum_sha256
        changed = await writer.execute(
            replace(document, source_entity_tag="different"),
            organization_public_id=UUID(int=2),
        )
        assert changed.storage_key != result.storage_key

    asyncio.run(run())


def test_concurrent_exact_publications_converge():
    async def run():
        storage = Storage()
        writer = WriteNormalizedArtifact(storage)
        results = await asyncio.gather(
            *(
                writer.execute(normalized(), organization_public_id=UUID(int=2))
                for _ in range(3)
            )
        )
        assert results[0] == results[1] == results[2]
        assert len(storage.objects) == 1
        assert storage.closed == 2

    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["size", "hash", "overflow", "short"])
def test_duplicate_corruption_fails_without_overwrite(corruption):
    async def run():
        storage = Storage()
        writer = WriteNormalizedArtifact(storage)
        result = await writer.execute(normalized(), organization_public_id=UUID(int=2))
        original = storage.objects[result.storage_key]
        if corruption == "size":
            storage.objects[result.storage_key] = b"bad"
        elif corruption == "hash":
            storage.objects[result.storage_key] = b"x" * len(original)
        else:
            storage.read_override = (
                original + b"overflow" if corruption == "overflow" else original[:-1]
            )
        with pytest.raises(DocumentNormalizationError) as exc:
            await writer.execute(normalized(), organization_public_id=UUID(int=2))
        assert exc.value.reason is Failure.ARTIFACT_MISMATCH
        assert storage.objects[result.storage_key] == (
            b"bad"
            if corruption == "size"
            else b"x" * len(original)
            if corruption == "hash"
            else original
        )
        assert storage.closed == (0 if corruption == "size" else 1)

    asyncio.run(run())


def test_conditional_read_change_propagates_and_closes_stream():
    async def run():
        storage = Storage()
        writer = WriteNormalizedArtifact(storage)
        await writer.execute(normalized(), organization_public_id=UUID(int=2))
        storage.read_failure = ObjectStorageError(reason=ObjectStorageFailure.CHANGED)
        with pytest.raises(ObjectStorageError) as exc:
            await writer.execute(normalized(), organization_public_id=UUID(int=2))
        assert exc.value is storage.read_failure
        assert storage.closed == 1

    asyncio.run(run())


def test_storage_failure_propagates_unchanged():
    async def run():
        storage = Storage()
        storage.failure = ObjectStorageError(reason=ObjectStorageFailure.TRANSIENT)
        with pytest.raises(ObjectStorageError) as exc:
            await WriteNormalizedArtifact(storage).execute(
                normalized(), organization_public_id=UUID(int=2)
            )
        assert exc.value is storage.failure
        assert not storage.objects

    asyncio.run(run())


def test_cancellation_after_remote_commit_and_identical_retry():
    async def run():
        storage = Storage()
        storage.commit_then_wait = True
        writer = WriteNormalizedArtifact(storage)
        task = asyncio.create_task(
            writer.execute(normalized(), organization_public_id=UUID(int=2))
        )
        await asyncio.wait_for(storage.started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(storage.objects) == 1
        storage.commit_then_wait = False
        result = await writer.execute(normalized(), organization_public_id=UUID(int=2))
        assert result.storage_key in storage.objects
        assert storage.closed == 1
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(run())


def test_verification_cancellation_closes_stream():
    async def run():
        storage = Storage()
        writer = WriteNormalizedArtifact(storage)
        await writer.execute(normalized(), organization_public_id=UUID(int=2))
        entered, closed = asyncio.Event(), asyncio.Event()

        async def waiting(**kwargs):
            try:
                yield b"{"
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        storage.stream_object = waiting
        task = asyncio.create_task(
            writer.execute(normalized(), organization_public_id=UUID(int=2))
        )
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()

    asyncio.run(run())


@pytest.mark.parametrize(
    "limit", ["max_artifact_bytes", "max_text_bytes", "max_blocks"]
)
def test_writer_bounds_prevent_storage_io(limit):
    async def run():
        storage = Storage()
        document = normalized()
        if limit == "max_blocks":
            document = NormalizeDocument().execute(
                ExtractedDocument(
                    UUID(int=1),
                    "etag",
                    "nexus.txt",
                    "1",
                    (
                        ExtractedBlock(0, Kind.TEXT, "a", 1, 2),
                        ExtractedBlock(1, Kind.TEXT, "b", 2, 3),
                    ),
                )
            )
        with pytest.raises(DocumentNormalizationError) as exc:
            await WriteNormalizedArtifact(storage, **{limit: 1}).execute(
                document, organization_public_id=UUID(int=2)
            )
        assert exc.value.reason is Failure.RESOURCE_LIMIT
        assert not storage.creates

    asyncio.run(run())


@pytest.mark.parametrize("name", ["max_artifact_bytes", "max_text_bytes", "max_blocks"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_writer_limits(name, value):
    with pytest.raises(ValueError):
        WriteNormalizedArtifact(Storage(), **{name: value})


@pytest.mark.parametrize("organization", [UUID(int=0), "untrusted/path", True])
def test_invalid_organization_prevents_storage_io(organization):
    storage = Storage()
    with pytest.raises(ValueError):
        asyncio.run(
            WriteNormalizedArtifact(storage).execute(
                normalized(), organization_public_id=organization
            )
        )
    assert not storage.creates


@pytest.mark.parametrize(
    "kwargs",
    [
        {"organization_public_id": UUID(int=0)},
        {"source_file_public_id": "invalid"},
        {"checksum_sha256": "x" * 64},
        {"checksum_sha256": 1},
        {"size_bytes": True},
        {"size_bytes": 0},
        {"schema_version": True},
        {"schema_version": 0},
        {"normalizer_version": " "},
    ],
)
def test_artifact_reference_validation(kwargs):
    async def run():
        result = await WriteNormalizedArtifact(Storage()).execute(
            normalized(), organization_public_id=UUID(int=2)
        )
        with pytest.raises(ValueError):
            replace(result, **kwargs)

    asyncio.run(run())


def test_exact_artifact_limit_and_escaping_expansion():
    async def run():
        document = normalized("\x01" * 8193)
        size = sum(len(chunk) for chunk in canonical_artifact_chunks(document))
        storage = Storage()
        result = await WriteNormalizedArtifact(
            storage, max_artifact_bytes=size
        ).execute(document, organization_public_id=UUID(int=2))
        assert result.size_bytes == size
        storage = Storage()
        with pytest.raises(DocumentNormalizationError) as exc:
            await WriteNormalizedArtifact(storage, max_artifact_bytes=size - 1).execute(
                document, organization_public_id=UUID(int=2)
            )
        assert exc.value.reason is Failure.RESOURCE_LIMIT
        assert not storage.creates

    asyncio.run(run())
