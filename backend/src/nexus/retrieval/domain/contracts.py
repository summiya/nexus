"""Retrieval values; tenant consistency is not proof of resource authorization."""

from dataclasses import dataclass
from uuid import UUID

from nexus.documents.domain.segmented_document import DocumentChunkCandidate

MAX_QUERY_LENGTH = 8192
MAX_TOP_K = 100


def _require_uuid(value: object) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("Retrieval requires a nonzero public UUID")


def _require_text(value: object, maximum: int) -> None:
    if not isinstance(value, str) or len(value) > maximum or not value.strip():
        raise ValueError("Retrieval requires bounded meaningful text")


@dataclass(frozen=True)
class RetrievalScope:
    """Trusted application tenant context, never a document permission grant."""

    organization_public_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(self.organization_public_id)


@dataclass(frozen=True, repr=False)
class RetrievalRequest:
    """Original query text and final result limit, independent of search strategy."""

    scope: RetrievalScope
    query: str
    top_k: int

    def __post_init__(self) -> None:
        if not isinstance(self.scope, RetrievalScope):
            raise TypeError("Retrieval requires an explicit tenant scope")
        _require_text(self.query, MAX_QUERY_LENGTH)
        if type(self.top_k) is not int or not 1 <= self.top_k <= MAX_TOP_K:
            raise ValueError("Retrieval top_k must be an integer from 1 to 100")


@dataclass(frozen=True, repr=False)
class RetrievedChunk:
    """One authoritative chunk with public generation identity and source facts."""

    organization_public_id: UUID
    document_public_id: UUID
    source_file_public_id: UUID
    chunk: DocumentChunkCandidate
    source_entity_tag: str
    processing_version: str
    extractor_id: str
    extractor_version: str
    normalizer_id: str
    normalizer_version: str
    segmenter_id: str
    segmenter_version: str
    preferred_chunk_bytes: int
    max_chunk_bytes: int
    max_source_contributions: int
    page_count: int | None = None

    def __post_init__(self) -> None:
        for identity in (
            self.organization_public_id,
            self.document_public_id,
            self.source_file_public_id,
        ):
            _require_uuid(identity)
        if not isinstance(self.chunk, DocumentChunkCandidate):
            raise TypeError("Retrieval requires an authoritative chunk candidate")
        _require_text(self.processing_version, 128)
        if self.processing_version != self.processing_version.strip():
            raise ValueError("Invalid processing version")
        for value in (
            self.source_entity_tag,
            self.extractor_id,
            self.extractor_version,
            self.normalizer_id,
            self.normalizer_version,
            self.segmenter_id,
            self.segmenter_version,
        ):
            _require_text(value, 1024)
        if (
            any(
                type(value) is not int or value < 1
                for value in (
                    self.preferred_chunk_bytes,
                    self.max_chunk_bytes,
                    self.max_source_contributions,
                )
            )
            or self.preferred_chunk_bytes > self.max_chunk_bytes
            or len(self.chunk.text.encode("utf-8")) > self.max_chunk_bytes
            or len(self.chunk.contributions) > self.max_source_contributions
        ):
            raise ValueError("Invalid retrieved chunk bounds")
        if self.page_count is not None and (
            type(self.page_count) is not int
            or self.page_count < 1
            or not self.chunk.page_numbers
            or any(page > self.page_count for page in self.chunk.page_numbers)
        ):
            raise ValueError("Invalid retrieved chunk page count")

    @property
    def chunk_index(self) -> int:
        return self.chunk.index

    @property
    def identity(self) -> tuple[UUID, int]:
        """Reprocessing creates a new Document UUID, preserving prior identities."""
        return self.document_public_id, self.chunk.index


@dataclass(frozen=True, repr=False)
class RetrievalResult:
    """Unique, tenant-consistent chunks in final ranking order; no score scale."""

    request: RetrievalRequest
    chunks: tuple[RetrievedChunk, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, RetrievalRequest):
            raise TypeError("Retrieval result requires its request")
        if not isinstance(self.chunks, tuple) or len(self.chunks) > self.request.top_k:
            raise ValueError("Retrieval result exceeds its requested bounds")
        identities: set[tuple[UUID, int]] = set()
        for chunk in self.chunks:
            if not isinstance(chunk, RetrievedChunk):
                raise TypeError("Retrieval result requires retrieved chunks")
            if (
                chunk.organization_public_id
                != self.request.scope.organization_public_id
            ):
                raise ValueError("Retrieval result tenant mismatch")
            if chunk.identity in identities:
                raise ValueError("Retrieval result contains duplicate chunk identities")
            identities.add(chunk.identity)
