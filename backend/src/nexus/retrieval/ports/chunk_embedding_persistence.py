"""A durable, bounded persistence boundary for V1 document chunk embeddings."""

from typing import Protocol
from uuid import UUID

from nexus.retrieval.domain.chunk_embeddings import ChunkEmbeddingBatch


class ChunkEmbeddingPersistenceError(Exception):
    def __init__(self) -> None:
        super().__init__("Chunk embedding persistence failed")


class ChunkEmbeddingConflictError(ChunkEmbeddingPersistenceError):
    def __init__(self) -> None:
        Exception.__init__(self, "Chunk embedding persistence conflict")


class StoredChunkEmbeddingCorruptionError(ChunkEmbeddingPersistenceError):
    def __init__(self) -> None:
        Exception.__init__(self, "Stored chunk embedding data is invalid")


class ChunkEmbeddingPersistence(Protocol):
    async def persist_batch(self, batch: ChunkEmbeddingBatch) -> None: ...

    async def read_batch(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
        configured_model_public_id: UUID,
        embedding_generation: int,
        chunk_indices: tuple[int, ...],
    ) -> ChunkEmbeddingBatch | None: ...
