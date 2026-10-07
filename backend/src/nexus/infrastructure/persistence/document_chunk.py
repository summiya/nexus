"""Bounded, atomic persistence of one immutable chunk set per Document."""

import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.domain import Document, DocumentStatus
from nexus.documents.domain.segmented_document import SegmentedDocument
from nexus.documents.ports.chunk_persistence import (
    ChunkConflictError,
    ChunkPersistenceError,
    DocumentChunkPersistence,
)
from nexus.documents.ports.persistence import DocumentPersistenceError
from nexus.infrastructure.persistence import _document_chunk_queries as queries
from nexus.infrastructure.persistence import _document_queries
from nexus.infrastructure.persistence.models.document_chunk import DocumentChunkSet


class SqlAlchemyDocumentChunkPersistence(DocumentChunkPersistence):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_chunks: int = 10_000,
        max_text_bytes: int = 16 * 1024 * 1024,
        max_contributions_per_chunk: int = 128,
        max_total_contributions: int = 60_000,
        max_provenance_bytes: int = 16 * 1024 * 1024,
        batch_size: int = 200,
    ) -> None:
        if any(
            type(v) is not int or v < 1
            for v in (
                max_chunks,
                max_text_bytes,
                max_contributions_per_chunk,
                max_total_contributions,
                max_provenance_bytes,
                batch_size,
            )
        ):
            raise ValueError("Invalid chunk persistence limits")
        self._sessions = session_factory
        self._max_chunks = max_chunks
        self._max_text = max_text_bytes
        self._max_per_chunk = max_contributions_per_chunk
        self._max_total = max_total_contributions
        self._max_provenance = max_provenance_bytes
        self._batch_size = batch_size

    def _check_sizes(
        self, count: int, text: int, per_chunk: int, total: int, provenance: int
    ) -> None:
        if (
            count > self._max_chunks
            or text > self._max_text
            or per_chunk > self._max_per_chunk
            or total > self._max_total
            or provenance > self._max_provenance
        ):
            raise ChunkPersistenceError()

    def _preflight(self, document: SegmentedDocument) -> list[dict[str, Any]]:
        self._check_sizes(len(document.chunks), 0, 0, 0, 0)
        rows = []
        text_bytes = total = provenance_bytes = 0
        encoder = json.JSONEncoder(ensure_ascii=False)
        try:
            for chunk in document.chunks:
                total += len(chunk.contributions)
                self._check_sizes(
                    len(document.chunks),
                    text_bytes,
                    len(chunk.contributions),
                    total,
                    provenance_bytes,
                )
                for start in range(0, len(chunk.text), 8192):
                    text_bytes += len(chunk.text[start : start + 8192].encode("utf-8"))
                    self._check_sizes(
                        len(document.chunks),
                        text_bytes,
                        len(chunk.contributions),
                        total,
                        provenance_bytes,
                    )
                row = queries.chunk_values(chunk)
                for part in encoder.iterencode(row["contributions"]):
                    provenance_bytes += len(part.encode("utf-8"))
                    self._check_sizes(
                        len(document.chunks),
                        text_bytes,
                        len(chunk.contributions),
                        total,
                        provenance_bytes,
                    )
                rows.append(row)
            return rows
        except (ValueError, TypeError, OverflowError) as exc:
            raise ChunkPersistenceError() from exc

    async def persist_chunk_set(
        self, *, expected: Document, segmented_document: SegmentedDocument
    ) -> None:
        rows = self._preflight(segmented_document)
        if (
            expected.status is not DocumentStatus.PROCESSING
            or expected.extractor_version is None
            or expected.extractor_version != segmented_document.extractor_version
            or expected.source_file_public_id
            != segmented_document.source_file_public_id
        ):
            raise ChunkConflictError()
        transaction = asyncio.create_task(
            self._persist(expected, segmented_document, rows)
        )
        try:
            await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_transaction(transaction)
            raise

    async def _persist(
        self,
        expected: Document,
        document: SegmentedDocument,
        rows: list[dict[str, Any]],
    ) -> None:
        try:
            async with self._sessions.begin() as session:
                locked = await _document_queries.document_for_update(
                    session,
                    organization_public_id=expected.organization_public_id,
                    document_public_id=expected.public_id,
                )
                if locked is None or locked[1] != expected:
                    raise ChunkConflictError()
                model, current = locked
                metadata = await queries.get_set(
                    session, document_id=model.id, organization_id=model.organization_id
                )
                if metadata is not None:
                    stored = await self._load(session, current, metadata)
                    if stored != document:
                        raise ChunkConflictError()
                    return
                session.add(
                    DocumentChunkSet(
                        document_id=model.id,
                        organization_id=model.organization_id,
                        **queries.set_values(document),
                    )
                )
                await session.flush()
                for start in range(0, len(rows), self._batch_size):
                    batch = [
                        dict(
                            row,
                            document_id=model.id,
                            organization_id=model.organization_id,
                        )
                        for row in rows[start : start + self._batch_size]
                    ]
                    await queries.insert_chunks(session, batch)
                await session.flush()
        except (SQLAlchemyError, DocumentPersistenceError) as exc:
            raise ChunkPersistenceError() from exc
        except (ValueError, TypeError, OverflowError) as exc:
            raise ChunkPersistenceError() from exc

    async def _load(
        self, session: AsyncSession, document: Document, metadata: DocumentChunkSet
    ) -> SegmentedDocument:
        return await queries.load_set(
            session,
            document,
            metadata,
            max_chunks=self._max_chunks,
            max_text_bytes=self._max_text,
            max_contributions_per_chunk=self._max_per_chunk,
            max_total_contributions=self._max_total,
            max_provenance_bytes=self._max_provenance,
        )

    async def get_chunk_set(
        self, *, organization_public_id: UUID, document_public_id: UUID
    ) -> SegmentedDocument | None:
        try:
            async with self._sessions() as session:
                document = await _document_queries.get_document(
                    session,
                    organization_public_id=organization_public_id,
                    document_public_id=document_public_id,
                )
                if document is None:
                    return None
                metadata = await queries.get_owned_set(
                    session,
                    organization_public_id=organization_public_id,
                    document_public_id=document_public_id,
                )
                if metadata is None:
                    return None
                return await self._load(session, document, metadata)
        except SQLAlchemyError as exc:
            raise ChunkPersistenceError() from exc
        except (ValueError, TypeError, OverflowError) as exc:
            raise ChunkPersistenceError() from exc
        except DocumentPersistenceError as exc:
            raise ChunkPersistenceError() from exc


async def _settle_transaction(transaction: asyncio.Task[None]) -> None:
    """Consume completion before propagating cancellation; never detach DB work."""
    while not transaction.done():
        try:
            await asyncio.shield(transaction)
        except asyncio.CancelledError:
            continue
        except BaseException:  # noqa: BLE001 - caller cancellation remains authoritative
            return
    if not transaction.cancelled():
        transaction.exception()
