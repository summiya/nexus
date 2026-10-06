"""Two-pass canonical JSON publication through the existing storage boundary."""

import hashlib
import json
from collections.abc import AsyncGenerator, Iterator
from contextlib import aclosing
from uuid import UUID

from nexus.documents.application.normalize_document import (
    DEFAULT_MAX_NORMALIZATION_BLOCKS,
    DEFAULT_MAX_NORMALIZATION_BYTES,
    DocumentNormalizationError,
    DocumentNormalizationFailure,
    text_size_bytes,
)
from nexus.documents.domain.normalized_document import (
    NormalizedArtifactReference,
    NormalizedBlock,
    NormalizedDocument,
)
from nexus.files.ports.storage import ObjectStorage, ObjectStorageAlreadyExistsError

ARTIFACT_SCHEMA_VERSION = 1
DEFAULT_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _block_fields(block: NormalizedBlock) -> dict[str, object]:
    item = block.list_item
    return {
        "source_block_index": block.source_block_index,
        "kind": block.kind.value,
        "text": block.text,
        "start_line": block.start_line,
        "end_line": block.end_line,
        "page_number": block.page_number,
        "heading_level": block.heading_level,
        "list_item": None
        if item is None
        else {
            "list_start_line": item.list_start_line,
            "item_start_line": item.item_start_line,
            "depth": item.depth,
            "ordered": item.ordered,
            "ordinal": item.ordinal,
        },
        "quote_depth": block.quote_depth,
        "section_path": block.section_path,
    }


def _block_chunks(block: NormalizedBlock) -> Iterator[bytes]:
    yield b"{"
    for index, (name, value) in enumerate(sorted(_block_fields(block).items())):
        if index:
            yield b","
        yield _json_bytes(name) + b":"
        if name == "text":
            # JSON escaping can expand text sixfold. Bound each encoded piece,
            # rather than encoding a complete potentially oversized block.
            yield b'"'
            for start in range(0, len(block.text), 8192):
                yield _json_bytes(block.text[start : start + 8192])[1:-1]
            yield b'"'
        else:
            yield _json_bytes(value)
    yield b"}"


def canonical_artifact_chunks(document: NormalizedDocument) -> Iterator[bytes]:
    """Explicit v1 schema; sorted keys and ordered blocks on both passes."""
    fields: dict[str, object] = {
        "extractor_id": document.extractor_id,
        "extractor_version": document.extractor_version,
        "normalizer_id": document.normalizer_id,
        "normalizer_version": document.normalizer_version,
        "page_count": document.page_count,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "source_entity_tag": document.source_entity_tag,
        "source_file_public_id": str(document.source_file_public_id),
    }
    yield b'{"blocks":['
    for index, block in enumerate(document.blocks):
        if index:
            yield b","
        yield from _block_chunks(block)
    yield b"]"
    for name, value in sorted(fields.items()):
        yield b"," + _json_bytes(name) + b":" + _json_bytes(value)
    yield b"}"


class WriteNormalizedArtifact:
    def __init__(
        self,
        object_storage: ObjectStorage,
        *,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
        max_blocks: int = DEFAULT_MAX_NORMALIZATION_BLOCKS,
        max_text_bytes: int = DEFAULT_MAX_NORMALIZATION_BYTES,
    ) -> None:
        if any(
            type(value) is not int or value < 1
            for value in (max_artifact_bytes, max_blocks, max_text_bytes)
        ):
            raise ValueError("Invalid artifact limits")
        self._storage = object_storage
        self._max_artifact_bytes = max_artifact_bytes
        self._max_blocks = max_blocks
        self._max_text_bytes = max_text_bytes

    async def execute(
        self,
        document: NormalizedDocument,
        *,
        organization_public_id: UUID,
    ) -> NormalizedArtifactReference:
        """The caller supplies an organization from trusted processing context."""
        if (
            not isinstance(organization_public_id, UUID)
            or not organization_public_id.int
        ):
            raise ValueError("Invalid artifact organization")
        if len(document.blocks) > self._max_blocks:
            raise DocumentNormalizationError(
                DocumentNormalizationFailure.RESOURCE_LIMIT
            )
        text_bytes = 0
        for block in document.blocks:
            text_bytes += text_size_bytes(
                block.text, maximum=self._max_text_bytes - text_bytes
            )
        size = 0
        digest = hashlib.sha256()
        for chunk in canonical_artifact_chunks(document):
            size += len(chunk)
            if size > self._max_artifact_bytes:
                raise DocumentNormalizationError(
                    DocumentNormalizationFailure.RESOURCE_LIMIT
                )
            digest.update(chunk)
        checksum = digest.hexdigest()
        key = (
            f"documents/{organization_public_id}/{document.source_file_public_id}"
            f"/normalized/v{ARTIFACT_SCHEMA_VERSION}/{checksum}.json"
        )

        async def content() -> AsyncGenerator[bytes, None]:
            for chunk in canonical_artifact_chunks(document):
                yield chunk

        try:
            async with aclosing(content()) as stream:
                await self._storage.create_object(storage_key=key, content=stream)
        except ObjectStorageAlreadyExistsError:
            await self._verify_existing(key, size, checksum)
        return NormalizedArtifactReference(
            organization_public_id,
            document.source_file_public_id,
            document.source_entity_tag,
            key,
            checksum,
            size,
            ARTIFACT_SCHEMA_VERSION,
            document.extractor_id,
            document.extractor_version,
            document.normalizer_id,
            document.normalizer_version,
        )

    async def _verify_existing(
        self, key: str, expected_size: int, checksum: str
    ) -> None:
        properties = await self._storage.get_object_properties(storage_key=key)
        if properties.size_bytes != expected_size:
            raise DocumentNormalizationError(
                DocumentNormalizationFailure.ARTIFACT_MISMATCH
            )
        size = 0
        digest = hashlib.sha256()
        stream = self._storage.stream_object(
            storage_key=key, expected_entity_tag=properties.entity_tag
        )
        try:
            async for chunk in stream:
                size += len(chunk)
                if size > expected_size:
                    raise DocumentNormalizationError(
                        DocumentNormalizationFailure.ARTIFACT_MISMATCH
                    )
                digest.update(chunk)
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        if size != expected_size or digest.hexdigest() != checksum:
            raise DocumentNormalizationError(
                DocumentNormalizationFailure.ARTIFACT_MISMATCH
            )
