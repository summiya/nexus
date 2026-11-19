"""Short, Document-first transactions for durable indexing snapshots only."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TypeVar
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.domain import DocumentStatus
from nexus.documents.ports.persistence import DocumentPersistenceError
from nexus.infrastructure.persistence import (
    _chunk_embedding_queries as embedding_queries,
)
from nexus.infrastructure.persistence import _document_chunk_queries, _document_queries
from nexus.infrastructure.persistence._transaction import _settle_cancelled_transaction
from nexus.infrastructure.persistence.models.chunk_embedding import ChunkEmbedding
from nexus.infrastructure.persistence.models.document import Document
from nexus.infrastructure.persistence.models.document_chunk import DocumentChunk
from nexus.infrastructure.persistence.models.indexing_generation import (
    IndexingGeneration as GenerationRow,
)
from nexus.infrastructure.persistence.models.model_provider import ConfiguredModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.retrieval.domain.chunk_embeddings import (
    V1_EMBEDDING_DIMENSION,
    V1_PROVIDER_MODEL_NAME,
    V1_PROVIDER_TYPE,
)
from nexus.retrieval.domain.indexing import (
    IndexingGeneration,
    IndexingStatus,
    require_indexing_identity,
)
from nexus.retrieval.ports.indexing_persistence import (
    IndexingConflictError,
    IndexingPersistence,
    IndexingPersistenceError,
)

T = TypeVar("T")


class SqlAlchemyIndexingPersistence(IndexingPersistence):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def create_generation(
        self, generation: IndexingGeneration
    ) -> IndexingGeneration:
        if not isinstance(generation, IndexingGeneration):
            raise TypeError("Expected a validated indexing generation")
        if generation.status is not IndexingStatus.PENDING:
            raise IndexingConflictError()
        return await self._run_transaction(
            lambda session: self._create(session, generation)
        )

    async def _create(
        self, session: AsyncSession, generation: IndexingGeneration
    ) -> IndexingGeneration:
        document = await _eligible_document(session, generation)
        row = await _find_row(session, generation.identity, lock=True)
        if row is not None:
            current = _to_domain(row, generation.identity)
            initial = replace(
                current,
                status=IndexingStatus.PENDING,
                started_at=None,
                finished_at=None,
                failure_code=None,
            )
            if initial != generation:
                raise IndexingConflictError()
            return current

        model_id = await _eligible_model(session, document.organization_id, generation)
        scope = (
            GenerationRow.organization_id == document.organization_id,
            GenerationRow.document_id == document.id,
            GenerationRow.configured_model_id == model_id,
        )
        if await session.scalar(
            select(
                exists().where(
                    *scope, GenerationRow.status.in_(("pending", "processing"))
                )
            )
        ):
            raise IndexingConflictError()
        tracked_max = await session.scalar(
            select(func.max(GenerationRow.embedding_generation)).where(*scope)
        )
        legacy_max = await session.scalar(
            select(func.max(ChunkEmbedding.embedding_generation))
            .join(
                DocumentChunk,
                (DocumentChunk.id == ChunkEmbedding.chunk_id)
                & (DocumentChunk.organization_id == ChunkEmbedding.organization_id),
            )
            .where(
                ChunkEmbedding.organization_id == document.organization_id,
                DocumentChunk.document_id == document.id,
                ChunkEmbedding.configured_model_id == model_id,
            )
        )
        if (
            generation.embedding_generation
            != max(tracked_max or 0, legacy_max or 0) + 1
        ):
            raise IndexingConflictError()
        row = GenerationRow(
            organization_id=document.organization_id,
            document_id=document.id,
            configured_model_id=model_id,
            embedding_generation=generation.embedding_generation,
            model_type="embedding",
            provider_type=generation.provider_type,
            provider_model_name=generation.provider_model_name,
            embedding_dimension=generation.embedding_dimension,
            embedding_version=generation.embedding_version,
            created_at=generation.created_at,
            **_lifecycle_values(generation),
        )
        session.add(row)
        await session.flush()
        return generation

    async def get_generation(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
        configured_model_public_id: UUID,
        embedding_generation: int,
    ) -> IndexingGeneration | None:
        identity = (
            organization_public_id,
            document_public_id,
            configured_model_public_id,
            embedding_generation,
        )
        require_indexing_identity(*identity)
        try:
            async with self._sessions() as session:
                row = await _find_row(session, identity, lock=False)
                return None if row is None else _to_domain(row, identity)
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            raise IndexingPersistenceError() from exc

    async def update_generation(
        self, *, expected: IndexingGeneration, generation: IndexingGeneration
    ) -> None:
        if not isinstance(expected, IndexingGeneration) or not isinstance(
            generation, IndexingGeneration
        ):
            raise TypeError("Expected validated indexing snapshots")
        if not expected.is_immediate_successor(generation):
            raise IndexingConflictError()
        await self._run_transaction(
            lambda session: self._update(session, expected, generation)
        )

    async def _update(
        self,
        session: AsyncSession,
        expected: IndexingGeneration,
        generation: IndexingGeneration,
    ) -> None:
        document = await _eligible_document(session, expected)
        row = await _find_row(session, expected.identity, lock=True)
        if row is None:
            raise IndexingConflictError()
        current = _to_domain(row, expected.identity)
        if current == generation:
            return  # Replay of the exact already-durable transition, including timestamps.
        if current != expected:
            raise IndexingConflictError()
        if generation.status is IndexingStatus.PROCESSING:
            await _eligible_model(session, document.organization_id, generation)
        elif generation.status is IndexingStatus.COMPLETED:
            await _require_coverage(session, document, row, generation)
        for key, value in _lifecycle_values(generation).items():
            setattr(row, key, value)
        await session.flush()

    async def _run_transaction(
        self, operation: Callable[[AsyncSession], Awaitable[T]]
    ) -> T:
        transaction = asyncio.create_task(self._execute(operation))
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _execute(self, operation: Callable[[AsyncSession], Awaitable[T]]) -> T:
        try:
            async with self._sessions.begin() as session:
                return await operation(session)
        except IntegrityError as exc:
            name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if name in ("pk_indexing_generations", "uq_indexing_generations_active"):
                raise IndexingConflictError() from exc
            raise IndexingPersistenceError() from exc
        except (
            SQLAlchemyError,
            DocumentPersistenceError,
            ValueError,
            TypeError,
            OverflowError,
        ) as exc:
            raise IndexingPersistenceError() from exc


async def _eligible_document(
    session: AsyncSession, generation: IndexingGeneration
) -> Document:
    locked = await _document_queries.document_for_update(
        session,
        organization_public_id=generation.organization_public_id,
        document_public_id=generation.document_public_id,
    )
    if locked is None or locked[1].status is not DocumentStatus.COMPLETED:
        raise IndexingConflictError()
    document, snapshot = locked
    if (
        snapshot.processing_completed_at is None
        or generation.created_at < snapshot.processing_completed_at
    ):
        raise IndexingConflictError()
    chunk_set = await _document_chunk_queries.get_set(
        session, document_id=document.id, organization_id=document.organization_id
    )
    count, first, last = (
        await session.execute(
            select(
                func.count(),
                func.min(DocumentChunk.chunk_index),
                func.max(DocumentChunk.chunk_index),
            ).where(
                DocumentChunk.organization_id == document.organization_id,
                DocumentChunk.document_id == document.id,
            )
        )
    ).one()
    if (
        chunk_set is None
        or count != chunk_set.chunk_count
        or first != 0
        or last != count - 1
    ):
        raise IndexingConflictError()
    return document


async def _eligible_model(
    session: AsyncSession, organization_id: int, generation: IndexingGeneration
) -> int:
    # The lifecycle domain is model-neutral. Admission currently targets RF-05's
    # V1 storage profile, without duplicating or generalizing its vector contract.
    if (
        generation.provider_type,
        generation.provider_model_name,
        generation.embedding_dimension,
    ) != (V1_PROVIDER_TYPE, V1_PROVIDER_MODEL_NAME, V1_EMBEDDING_DIMENSION):
        raise IndexingConflictError()
    model = await embedding_queries.locked_model_snapshot(
        session,
        organization_id=organization_id,
        model_public_id=generation.configured_model_public_id,
    )
    if (
        model is None
        or model[1:4]
        != (
            generation.provider_type,
            generation.provider_model_name,
            generation.embedding_dimension,
        )
        or not model[4]
        or not model[5]
    ):
        raise IndexingConflictError()
    return model[0]


async def _find_row(
    session: AsyncSession, identity: tuple[UUID, UUID, UUID, int], *, lock: bool
) -> GenerationRow | None:
    organization_public_id, document_public_id, model_public_id, generation = identity
    statement = (
        select(GenerationRow)
        .join(
            Document,
            (Document.id == GenerationRow.document_id)
            & (Document.organization_id == GenerationRow.organization_id),
        )
        .join(Organization, Organization.id == GenerationRow.organization_id)
        .join(
            ConfiguredModel,
            (ConfiguredModel.id == GenerationRow.configured_model_id)
            & (ConfiguredModel.organization_id == GenerationRow.organization_id),
        )
        .where(
            Organization.public_id == organization_public_id,
            Document.public_id == document_public_id,
            ConfiguredModel.public_id == model_public_id,
            GenerationRow.embedding_generation == generation,
        )
    )
    if lock:
        statement = statement.with_for_update(of=GenerationRow)
    return await session.scalar(statement)


async def _require_coverage(
    session: AsyncSession,
    document: Document,
    row: GenerationRow,
    generation: IndexingGeneration,
) -> None:
    authoritative = select(DocumentChunk.id).where(
        DocumentChunk.organization_id == document.organization_id,
        DocumentChunk.document_id == document.id,
    )
    stored = (
        select(ChunkEmbedding.chunk_id)
        .join(
            DocumentChunk,
            (DocumentChunk.id == ChunkEmbedding.chunk_id)
            & (DocumentChunk.organization_id == ChunkEmbedding.organization_id),
        )
        .where(
            ChunkEmbedding.organization_id == document.organization_id,
            DocumentChunk.document_id == document.id,
            ChunkEmbedding.configured_model_id == row.configured_model_id,
            ChunkEmbedding.embedding_generation == generation.embedding_generation,
        )
    )
    if await session.scalar(
        select(exists(authoritative.except_(stored)))
    ) or await session.scalar(select(exists(stored.except_(authoritative)))):
        raise IndexingConflictError()
    headers = await embedding_queries.generation_snapshots(
        session,
        organization_id=document.organization_id,
        document_id=document.id,
        configured_model_id=row.configured_model_id,
        embedding_generation=generation.embedding_generation,
    )
    if headers != [generation.model_snapshot]:
        raise IndexingConflictError()


def _lifecycle_values(generation: IndexingGeneration) -> dict[str, object]:
    return {
        "status": generation.status.value,
        "started_at": generation.started_at,
        "finished_at": generation.finished_at,
        "failure_code": generation.failure_code,
    }


def _to_domain(
    row: GenerationRow, identity: tuple[UUID, UUID, UUID, int]
) -> IndexingGeneration:
    return IndexingGeneration(
        organization_public_id=identity[0],
        document_public_id=identity[1],
        configured_model_public_id=identity[2],
        embedding_generation=identity[3],
        embedding_version=row.embedding_version,
        provider_type=row.provider_type,
        provider_model_name=row.provider_model_name,
        embedding_dimension=row.embedding_dimension,
        created_at=row.created_at,
        status=IndexingStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        failure_code=row.failure_code,
    )
