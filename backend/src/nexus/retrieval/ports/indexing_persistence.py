"""Durable indexing snapshots; callers supply authorized, trusted tenant context."""

from typing import Protocol
from uuid import UUID

from nexus.retrieval.domain.indexing import IndexingGeneration


class IndexingPersistenceError(Exception):
    def __init__(self) -> None:
        super().__init__("Indexing persistence failed")


class IndexingConflictError(IndexingPersistenceError):
    def __init__(self) -> None:
        Exception.__init__(self, "Indexing generation conflict")


class IndexingPersistence(Protocol):
    async def create_generation(
        self, generation: IndexingGeneration
    ) -> IndexingGeneration:
        """Reserve the next number, or return an identical creation's current state."""
        ...

    async def get_generation(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
        configured_model_public_id: UUID,
        embedding_generation: int,
    ) -> IndexingGeneration | None: ...

    async def update_generation(
        self, *, expected: IndexingGeneration, generation: IndexingGeneration
    ) -> None:
        """Atomically persist one successor; exact transition replays are no-ops."""
        ...
