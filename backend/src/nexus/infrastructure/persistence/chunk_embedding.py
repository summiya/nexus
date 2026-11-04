"""Atomic, idempotent, tenant-safe V1 chunk vector persistence.

RF-05 stores precomputed embedding vectors only. Provider execution,
worker orchestration, indexing and similarity retrieval are out of scope.
"""

from __future__ import annotations

import asyncio
from math import isfinite
from struct import error as StructError
from struct import pack, unpack
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.domain import DocumentStatus
from nexus.infrastructure.persistence import _chunk_embedding_queries as queries
from nexus.infrastructure.persistence import _document_chunk_queries, _document_queries
from nexus.infrastructure.persistence._transaction import _settle_cancelled_transaction
from nexus.retrieval.domain.chunk_embeddings import (
    ChunkEmbeddingBatch,
    ChunkEmbeddingVector,
    require_chunk_indices,
    require_generation,
    require_public_uuid,
)
from nexus.retrieval.ports.chunk_embedding_persistence import (
    ChunkEmbeddingConflictError,
    ChunkEmbeddingPersistence,
    ChunkEmbeddingPersistenceError,
    StoredChunkEmbeddingCorruptionError,
)

_UNIQUE_GENERATION_CONSTRAINT = "uq_chunk_embeddings_generation"


class SqlAlchemyChunkEmbeddingPersistence(ChunkEmbeddingPersistence):
    """Persist small batches without assuming a document fits in one invocation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def persist_batch(self, batch: ChunkEmbeddingBatch) -> None:
        if not isinstance(batch, ChunkEmbeddingBatch):
            raise TypeError("Expected a validated chunk embedding batch")

        # PostgreSQL pgvector stores float32, unlike Python's float64. Validate
        # the storage representation before acquiring locks, then compare exact
        # float32 values for deterministic duplicate semantics.
        try:
            canonical = {
                vector.chunk_index: _to_float32(vector.values)
                for vector in batch.vectors
            }
        except (TypeError, ValueError, OverflowError) as exc:
            raise ChunkEmbeddingPersistenceError() from exc

        transaction = asyncio.create_task(self._persist(batch, canonical))
        try:
            await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _persist(
        self, batch: ChunkEmbeddingBatch, canonical: dict[int, tuple[float, ...]]
    ) -> None:
        try:
            async with self._sessions.begin() as session:
                # Serializes competing writers to the same document, without
                # a database-wide lock or a cross-tenant lookup.
                locked = await _document_queries.document_for_update(
                    session,
                    organization_public_id=batch.organization_public_id,
                    document_public_id=batch.document_public_id,
                )
                if locked is None or locked[1].status is not DocumentStatus.COMPLETED:
                    raise ChunkEmbeddingConflictError()
                document, _ = locked

                chunk_set = await _document_chunk_queries.get_set(
                    session,
                    document_id=document.id,
                    organization_id=document.organization_id,
                )
                if chunk_set is None:
                    raise ChunkEmbeddingConflictError()

                model = await queries.locked_model_snapshot(
                    session,
                    organization_id=document.organization_id,
                    model_public_id=batch.configured_model_public_id,
                )
                if model is None:
                    raise ChunkEmbeddingConflictError()
                (
                    model_id,
                    provider_type,
                    provider_name,
                    dimension,
                    model_enabled,
                    provider_enabled,
                ) = model
                if (
                    provider_type != batch.provider_type
                    or provider_name != batch.provider_model_name
                    or dimension != batch.embedding_dimension
                ):
                    raise ChunkEmbeddingConflictError()

                chunk_ids = await queries.authoritative_chunks(
                    session,
                    organization_id=document.organization_id,
                    document_id=document.id,
                    chunk_indices=batch.chunk_indices,
                )
                if (
                    len(chunk_ids) != len(batch.vectors)
                    or batch.chunk_indices[-1] >= chunk_set.chunk_count
                ):
                    raise ChunkEmbeddingConflictError()

                expected_header = (
                    batch.embedding_version,
                    batch.provider_type,
                    batch.provider_model_name,
                    batch.embedding_dimension,
                )
                headers = await queries.generation_snapshots(
                    session,
                    organization_id=document.organization_id,
                    document_id=document.id,
                    configured_model_id=model_id,
                    embedding_generation=batch.embedding_generation,
                )
                if any(header != expected_header for header in headers):
                    raise ChunkEmbeddingConflictError()

                existing = await queries.existing_embeddings(
                    session,
                    organization_id=document.organization_id,
                    document_id=document.id,
                    configured_model_id=model_id,
                    embedding_generation=batch.embedding_generation,
                    chunk_indices=batch.chunk_indices,
                )
                to_insert: list[dict[str, object]] = []
                for vector in batch.vectors:
                    values = canonical[vector.chunk_index]
                    previous = existing.get(vector.chunk_index)
                    if previous is not None:
                        if (
                            previous.embedding_version != batch.embedding_version
                            or previous.provider_type != batch.provider_type
                            or previous.provider_model_name != batch.provider_model_name
                            or previous.embedding_dimension != batch.embedding_dimension
                            or tuple(float(value) for value in previous.embedding)
                            != values
                        ):
                            raise ChunkEmbeddingConflictError()
                        continue

                    to_insert.append(
                        {
                            "organization_id": document.organization_id,
                            "chunk_id": chunk_ids[vector.chunk_index],
                            "configured_model_id": model_id,
                            "model_type": "embedding",
                            "provider_type": batch.provider_type,
                            "provider_model_name": batch.provider_model_name,
                            "embedding_dimension": batch.embedding_dimension,
                            "embedding_generation": batch.embedding_generation,
                            "embedding_version": batch.embedding_version,
                            "embedding": list(values),
                        }
                    )

                # An already-durable retry remains safe when a model is later
                # disabled. New writes must still use an enabled configuration.
                if to_insert and (not model_enabled or not provider_enabled):
                    raise ChunkEmbeddingConflictError()
                if to_insert:
                    await queries.insert_embeddings(session, to_insert)
                    await session.flush()
        except IntegrityError as exc:
            if _constraint_name(exc) == _UNIQUE_GENERATION_CONSTRAINT:
                raise ChunkEmbeddingConflictError() from exc
            raise ChunkEmbeddingPersistenceError() from exc
        except SQLAlchemyError as exc:
            raise ChunkEmbeddingPersistenceError() from exc
        except (TypeError, ValueError, OverflowError) as exc:
            raise ChunkEmbeddingPersistenceError() from exc

    async def read_batch(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
        configured_model_public_id: UUID,
        embedding_generation: int,
        chunk_indices: tuple[int, ...],
    ) -> ChunkEmbeddingBatch | None:
        for identity in (
            organization_public_id,
            document_public_id,
            configured_model_public_id,
        ):
            require_public_uuid(identity)
        require_generation(embedding_generation)
        require_chunk_indices(chunk_indices)

        try:
            async with self._sessions() as session:
                rows = await queries.read_owned_embeddings(
                    session,
                    organization_public_id=organization_public_id,
                    document_public_id=document_public_id,
                    configured_model_public_id=configured_model_public_id,
                    embedding_generation=embedding_generation,
                    chunk_indices=chunk_indices,
                )
                if not rows:
                    return None
                first = rows[0][1]
                metadata = (
                    first.embedding_version,
                    first.provider_type,
                    first.provider_model_name,
                    first.embedding_dimension,
                )
                if any(
                    (
                        row.embedding_version,
                        row.provider_type,
                        row.provider_model_name,
                        row.embedding_dimension,
                    )
                    != metadata
                    for _, row in rows
                ):
                    raise StoredChunkEmbeddingCorruptionError()
                try:
                    return ChunkEmbeddingBatch(
                        organization_public_id=organization_public_id,
                        document_public_id=document_public_id,
                        configured_model_public_id=configured_model_public_id,
                        embedding_generation=embedding_generation,
                        embedding_version=first.embedding_version,
                        provider_type=first.provider_type,
                        provider_model_name=first.provider_model_name,
                        embedding_dimension=first.embedding_dimension,
                        vectors=tuple(
                            ChunkEmbeddingVector(
                                chunk_index=index,
                                values=tuple(float(value) for value in row.embedding),
                            )
                            for index, row in rows
                        ),
                    )
                except (TypeError, ValueError, OverflowError) as exc:
                    raise StoredChunkEmbeddingCorruptionError() from exc
        except SQLAlchemyError as exc:
            raise ChunkEmbeddingPersistenceError() from exc


def _to_float32(values: tuple[float, ...]) -> tuple[float, ...]:
    """Round exactly as pgvector's float32 storage without optional NumPy."""
    try:
        format_string = f"!{len(values)}f"
        canonical = unpack(format_string, pack(format_string, *values))
    except (OverflowError, StructError) as exc:
        raise ValueError("Invalid float32 chunk embedding") from exc
    if not all(isfinite(value) for value in canonical) or not any(canonical):
        raise ValueError("Invalid float32 chunk embedding")
    return canonical


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None
