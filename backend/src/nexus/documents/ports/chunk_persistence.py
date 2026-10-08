"""Persistence of one immutable chunk set per tenant-owned Document lifecycle."""

from typing import Protocol
from uuid import UUID

from nexus.documents.domain import Document
from nexus.documents.domain.segmented_document import SegmentedDocument


class ChunkPersistenceError(Exception):
    def __init__(self) -> None:
        super().__init__("Document chunk persistence failed")


class StoredChunkCorruptionError(ChunkPersistenceError):
    """Stored output was read successfully but violates reconstruction invariants."""

    def __init__(self) -> None:
        Exception.__init__(self, "The persisted processing output is invalid.")


class ChunkConflictError(ChunkPersistenceError):
    def __init__(self) -> None:
        Exception.__init__(self, "Document chunk persistence conflict")


class DocumentChunkPersistence(Protocol):
    async def persist_chunk_set(
        self, *, expected: Document, segmented_document: SegmentedDocument
    ) -> None: ...

    async def get_chunk_set(
        self, *, organization_public_id: UUID, document_public_id: UUID
    ) -> SegmentedDocument | None: ...
