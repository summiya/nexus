"""Tenant-filtered SQL queries for authoritative chunk embedding generations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.infrastructure.persistence.models.chunk_embedding import ChunkEmbedding
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.document_chunk import DocumentChunk
from nexus.infrastructure.persistence.models.model_provider import (
    ConfiguredModel,
    ModelProvider,
)
from nexus.infrastructure.persistence.models.organization import Organization


async def locked_model_snapshot(
    session: AsyncSession, *, organization_id: int, model_public_id: UUID
) -> tuple[int, str, str, int | None, bool, bool] | None:
    """Lock model/provider snapshots against concurrent configuration mutation."""
    row = (
        await session.execute(
            select(
                ConfiguredModel.id,
                ModelProvider.provider_type,
                ConfiguredModel.provider_model_name,
                ConfiguredModel.embedding_dimension,
                ConfiguredModel.enabled,
                ModelProvider.enabled,
            )
            .join(
                ModelProvider,
                (ModelProvider.id == ConfiguredModel.provider_id)
                & (ModelProvider.organization_id == ConfiguredModel.organization_id),
            )
            .where(
                ConfiguredModel.public_id == model_public_id,
                ConfiguredModel.organization_id == organization_id,
                ConfiguredModel.model_type == "embedding",
            )
            .with_for_update(read=True, of=(ConfiguredModel, ModelProvider))
        )
    ).one_or_none()
    if row is None:
        return None
    return row[0], row[1], row[2], row[3], row[4], row[5]


async def authoritative_chunks(
    session: AsyncSession,
    *,
    organization_id: int,
    document_id: int,
    chunk_indices: tuple[int, ...],
) -> dict[int, int]:
    result = await session.execute(
        select(DocumentChunk.chunk_index, DocumentChunk.id).where(
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.chunk_index.in_(chunk_indices),
        )
    )
    return {index: identity for index, identity in result.all()}


async def generation_snapshots(
    session: AsyncSession,
    *,
    organization_id: int,
    document_id: int,
    configured_model_id: int,
    embedding_generation: int,
) -> list[tuple[str, str, str, int]]:
    """All distinct headers; a mixed generation is a conflict, not a winner."""
    result = await session.execute(
        select(
            ChunkEmbedding.embedding_version,
            ChunkEmbedding.provider_type,
            ChunkEmbedding.provider_model_name,
            ChunkEmbedding.embedding_dimension,
        )
        .join(
            DocumentChunk,
            (DocumentChunk.id == ChunkEmbedding.chunk_id)
            & (DocumentChunk.organization_id == ChunkEmbedding.organization_id),
        )
        .where(
            ChunkEmbedding.organization_id == organization_id,
            DocumentChunk.document_id == document_id,
            ChunkEmbedding.configured_model_id == configured_model_id,
            ChunkEmbedding.embedding_generation == embedding_generation,
        )
        .distinct()
        .limit(2)
    )
    return [(version, provider, model, dimension) for version, provider, model, dimension in result.all()]


async def existing_embeddings(
    session: AsyncSession,
    *,
    organization_id: int,
    document_id: int,
    configured_model_id: int,
    embedding_generation: int,
    chunk_indices: tuple[int, ...],
) -> dict[int, ChunkEmbedding]:
    result = await session.execute(
        select(DocumentChunk.chunk_index, ChunkEmbedding)
        .join(
            ChunkEmbedding,
            (ChunkEmbedding.chunk_id == DocumentChunk.id)
            & (ChunkEmbedding.organization_id == DocumentChunk.organization_id),
        )
        .where(
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.chunk_index.in_(chunk_indices),
            ChunkEmbedding.configured_model_id == configured_model_id,
            ChunkEmbedding.embedding_generation == embedding_generation,
        )
    )
    return {index: row for index, row in result.all()}


async def insert_embeddings(
    session: AsyncSession, rows: list[dict[str, object]]
) -> None:
    await session.execute(insert(ChunkEmbedding), rows)


async def read_owned_embeddings(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    document_public_id: UUID,
    configured_model_public_id: UUID,
    embedding_generation: int,
    chunk_indices: tuple[int, ...],
) -> list[tuple[int, ChunkEmbedding]]:
    result = await session.execute(
        select(DocumentChunk.chunk_index, ChunkEmbedding)
        .join(
            ChunkEmbedding,
            (ChunkEmbedding.chunk_id == DocumentChunk.id)
            & (ChunkEmbedding.organization_id == DocumentChunk.organization_id),
        )
        .join(
            DocumentModel,
            (DocumentModel.id == DocumentChunk.document_id)
            & (DocumentModel.organization_id == DocumentChunk.organization_id),
        )
        .join(Organization, Organization.id == DocumentModel.organization_id)
        .join(
            ConfiguredModel,
            (ConfiguredModel.id == ChunkEmbedding.configured_model_id)
            & (ConfiguredModel.organization_id == ChunkEmbedding.organization_id),
        )
        .where(
            Organization.public_id == organization_public_id,
            DocumentModel.public_id == document_public_id,
            ConfiguredModel.public_id == configured_model_public_id,
            ChunkEmbedding.embedding_generation == embedding_generation,
            DocumentChunk.chunk_index.in_(chunk_indices),
        )
        .order_by(DocumentChunk.chunk_index)
    )
    return [(index, row) for index, row in result.all()]
