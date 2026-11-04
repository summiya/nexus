"""Bounded tenant-scoped V1 chunk embedding snapshots.

The shape follows RF-04's immutable PostgreSQL VECTOR(1536) schema. It does
not execute providers, make authorization decisions, or perform retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import isfinite
from uuid import UUID

MAX_EMBEDDINGS_PER_BATCH = 128
V1_EMBEDDING_DIMENSION = 1536
V1_PROVIDER_TYPE = "openai"
V1_PROVIDER_MODEL_NAME = "text-embedding-3-small"


def require_public_uuid(value: object) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("Embedding persistence requires nonzero public UUIDs")


def require_generation(value: object) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("Embedding generation must be a positive integer")


def require_chunk_indices(value: object) -> None:
    if not isinstance(value, tuple) or not (
        1 <= len(value) <= MAX_EMBEDDINGS_PER_BATCH
    ):
        raise ValueError("Chunk selection must contain 1 to 128 indexes")
    if any(type(index) is not int or index < 0 for index in value):
        raise ValueError("Chunk indexes must be nonnegative integers")
    if any(left >= right for left, right in pairwise(value)):
        raise ValueError("Chunk indexes must be unique and ascending")


@dataclass(frozen=True, slots=True, repr=False)
class ChunkEmbeddingVector:
    """One vector assigned to an authoritative chunk index, not arbitrary text."""

    chunk_index: int
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if type(self.chunk_index) is not int or self.chunk_index < 0:
            raise ValueError("Chunk index must be a nonnegative integer")
        if not isinstance(self.values, tuple) or len(self.values) != V1_EMBEDDING_DIMENSION:
            raise ValueError("V1 chunk embedding must contain 1536 values")
        if any(type(value) is not float or not isfinite(value) for value in self.values):
            raise ValueError("Chunk embedding requires finite float values")
        if not any(self.values):
            raise ValueError("Chunk embedding vector cannot be zero")


@dataclass(frozen=True, slots=True, repr=False)
class ChunkEmbeddingBatch:
    """One immutable invocation snapshot for 1-128 ordered document chunks.

    Multiple batches may fill the same document/model/generation. The adapter
    enforces consistent invocation metadata and exact idempotent vector values.
    """

    organization_public_id: UUID
    document_public_id: UUID
    configured_model_public_id: UUID
    embedding_generation: int
    embedding_version: str
    provider_type: str
    provider_model_name: str
    embedding_dimension: int
    vectors: tuple[ChunkEmbeddingVector, ...]

    def __post_init__(self) -> None:
        for value in (
            self.organization_public_id,
            self.document_public_id,
            self.configured_model_public_id,
        ):
            require_public_uuid(value)
        require_generation(self.embedding_generation)
        if (
            not isinstance(self.embedding_version, str)
            or not 1 <= len(self.embedding_version) <= 128
            or not self.embedding_version.strip()
            or self.embedding_version != self.embedding_version.strip()
        ):
            raise ValueError("Embedding version must be bounded and nonblank")
        if (
            self.provider_type != V1_PROVIDER_TYPE
            or self.provider_model_name != V1_PROVIDER_MODEL_NAME
            or type(self.embedding_dimension) is not int
            or self.embedding_dimension != V1_EMBEDDING_DIMENSION
        ):
            raise ValueError("Unsupported V1 embedding model snapshot")
        if (
            not isinstance(self.vectors, tuple)
            or any(not isinstance(v, ChunkEmbeddingVector) for v in self.vectors)
        ):
            raise ValueError("Embedding batch requires immutable chunk vectors")
        require_chunk_indices(tuple(v.chunk_index for v in self.vectors))

    @property
    def chunk_indices(self) -> tuple[int, ...]:
        return tuple(item.chunk_index for item in self.vectors)
