"""Explicit provenance codec and tenant-scoped chunk-set SQL queries."""

from typing import Any
from uuid import UUID

from sqlalchemy import Text, case, cast, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.documents.domain import Document
from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind,
    ExtractedListItem,
)
from nexus.documents.domain.segmented_document import (
    DocumentChunkCandidate,
    DocumentChunkKind,
    SegmentedDocument,
    SourceContribution,
)
from nexus.documents.ports.chunk_persistence import ChunkPersistenceError
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.document_chunk import (
    DocumentChunk,
    DocumentChunkSet,
)
from nexus.infrastructure.persistence.models.organization import Organization

_CONTRIBUTION_FIELDS = frozenset(
    {
        "source_block_index",
        "kind",
        "start_line",
        "end_line",
        "page_number",
        "list_item",
        "quote_depth",
        "text_start",
        "text_end",
    }
)
_LIST_FIELDS = frozenset(
    {"list_start_line", "item_start_line", "depth", "ordered", "ordinal"}
)


def encode_contribution(value: SourceContribution) -> dict[str, Any]:
    item = value.list_item
    return {
        "source_block_index": value.source_block_index,
        "kind": value.kind.value,
        "start_line": value.start_line,
        "end_line": value.end_line,
        "page_number": value.page_number,
        "list_item": None
        if item is None
        else {
            "list_start_line": item.list_start_line,
            "item_start_line": item.item_start_line,
            "depth": item.depth,
            "ordered": item.ordered,
            "ordinal": item.ordinal,
        },
        "quote_depth": value.quote_depth,
        "text_start": value.text_start,
        "text_end": value.text_end,
    }


def decode_contribution(value: object) -> SourceContribution:
    if not isinstance(value, dict) or value.keys() != _CONTRIBUTION_FIELDS:
        raise ValueError("Invalid stored contribution")
    item = value["list_item"]
    if item is not None:
        if not isinstance(item, dict) or item.keys() != _LIST_FIELDS:
            raise ValueError("Invalid stored list provenance")
        item = ExtractedListItem(**item)
    return SourceContribution(
        value["source_block_index"],
        ExtractedBlockKind(value["kind"]),
        value["start_line"],
        value["end_line"],
        value["page_number"],
        item,
        value["quote_depth"],
        value["text_start"],
        value["text_end"],
    )


def set_values(document: SegmentedDocument) -> dict[str, Any]:
    return {
        "source_entity_tag": document.source_entity_tag,
        "extractor_id": document.extractor_id,
        "extractor_version": document.extractor_version,
        "normalizer_id": document.normalizer_id,
        "normalizer_version": document.normalizer_version,
        "segmenter_id": document.segmenter_id,
        "segmenter_version": document.segmenter_version,
        "preferred_chunk_bytes": document.preferred_chunk_bytes,
        "max_chunk_bytes": document.max_chunk_bytes,
        "max_source_contributions": document.max_source_contributions,
        "page_count": document.page_count,
        "chunk_count": len(document.chunks),
    }


def chunk_values(chunk: DocumentChunkCandidate) -> dict[str, Any]:
    return {
        "chunk_index": chunk.index,
        "text": chunk.text,
        "kind": chunk.kind.value,
        "section_path": list(chunk.section_path),
        "contributions": [encode_contribution(c) for c in chunk.contributions],
    }


async def get_set(
    session: AsyncSession, *, document_id: int, organization_id: int
) -> DocumentChunkSet | None:
    return await session.scalar(
        select(DocumentChunkSet).where(
            DocumentChunkSet.document_id == document_id,
            DocumentChunkSet.organization_id == organization_id,
        )
    )


async def get_chunks(
    session: AsyncSession, *, document_id: int, organization_id: int, limit: int
) -> list[DocumentChunk]:
    return list(
        await session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.organization_id == organization_id,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
    )


async def insert_chunks(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await session.execute(insert(DocumentChunk), rows)


def to_segmented(
    document: Document, metadata: DocumentChunkSet, rows: list[DocumentChunk]
) -> SegmentedDocument:
    try:
        if len(rows) != metadata.chunk_count:
            raise ValueError("Incomplete stored chunk set")
        chunks = []
        for row in rows:
            if not isinstance(row.contributions, list):
                raise TypeError("Invalid stored contributions")
            chunks.append(
                DocumentChunkCandidate(
                    row.chunk_index,
                    DocumentChunkKind(row.kind),
                    row.text,
                    tuple(row.section_path),
                    tuple(decode_contribution(c) for c in row.contributions),
                )
            )
        # Explicit constructor mapping; ORM-only count/identity never cross the port.
        return SegmentedDocument(
            document.source_file_public_id,
            metadata.source_entity_tag,
            metadata.extractor_id,
            metadata.extractor_version,
            metadata.normalizer_id,
            metadata.normalizer_version,
            metadata.segmenter_id,
            metadata.segmenter_version,
            metadata.preferred_chunk_bytes,
            metadata.max_chunk_bytes,
            metadata.max_source_contributions,
            tuple(chunks),
            metadata.page_count,
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ChunkPersistenceError() from exc


async def get_owned_set(
    session: AsyncSession, *, organization_public_id: UUID, document_public_id: UUID
) -> DocumentChunkSet | None:
    return await session.scalar(
        select(DocumentChunkSet)
        .join(
            DocumentModel,
            (DocumentModel.id == DocumentChunkSet.document_id)
            & (DocumentModel.organization_id == DocumentChunkSet.organization_id),
        )
        .join(Organization, Organization.id == DocumentModel.organization_id)
        .where(
            Organization.public_id == organization_public_id,
            DocumentModel.public_id == document_public_id,
        )
    )


async def stored_sizes(
    session: AsyncSession, *, document_id: int, organization_id: int
) -> tuple[int, int, int, int, int]:
    contribution_count = case(
        (
            func.jsonb_typeof(DocumentChunk.contributions) == "array",
            func.jsonb_array_length(DocumentChunk.contributions),
        ),
        else_=0,
    )
    row = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(func.octet_length(DocumentChunk.text)), 0),
                func.coalesce(func.max(contribution_count), 0),
                func.coalesce(func.sum(contribution_count), 0),
                func.coalesce(
                    func.sum(
                        func.octet_length(cast(DocumentChunk.contributions, Text))
                    ),
                    0,
                ),
            ).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.organization_id == organization_id,
            )
        )
    ).one()
    return tuple(row)
