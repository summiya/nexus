"""Settle lifecycle under the same Document row lock as authoritative chunks."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.application.processing_failures import PROCESSING_OUTPUT_CORRUPT
from nexus.documents.domain import DocumentFailure, DocumentStatus
from nexus.documents.ports.chunk_persistence import StoredChunkCorruptionError
from nexus.documents.ports.persistence import (
    DocumentConflictError,
    DocumentPersistenceError,
)
from nexus.documents.ports.processing import (
    DocumentFinalization,
    ProcessingOutcome,
    ProcessingResult,
)
from nexus.infrastructure.persistence import _document_chunk_queries, _document_queries
from nexus.infrastructure.persistence._transaction import _settle_cancelled_transaction


class SqlAlchemyDocumentFinalization(DocumentFinalization):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def finalize(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
        failure: DocumentFailure | None = None,
    ) -> ProcessingResult:
        task = asyncio.create_task(
            self._finalize(organization_public_id, document_public_id, failure)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(task)
            raise

    async def _finalize(
        self,
        organization_public_id: UUID,
        document_public_id: UUID,
        failure: DocumentFailure | None,
    ) -> ProcessingResult:
        try:
            async with self._sessions.begin() as session:
                locked = await _document_queries.document_for_update(
                    session,
                    organization_public_id=organization_public_id,
                    document_public_id=document_public_id,
                )
                if locked is None:
                    raise DocumentConflictError("Document persistence conflict")
                model, current = locked
                if current.status in (DocumentStatus.COMPLETED, DocumentStatus.FAILED):
                    return ProcessingResult(ProcessingOutcome.SUCCESS)
                if current.status is not DocumentStatus.PROCESSING:
                    raise DocumentConflictError("Document persistence conflict")
                metadata = await _document_chunk_queries.get_set(
                    session,
                    document_id=model.id,
                    organization_id=model.organization_id,
                )
                at = max(
                    datetime.now(UTC),
                    current.processing_started_at or current.created_at,
                )
                if metadata is not None:
                    try:
                        await _document_chunk_queries.load_set(
                            session, current, metadata
                        )
                    except StoredChunkCorruptionError:
                        if failure is None:
                            raise
                        failure = PROCESSING_OUTPUT_CORRUPT.failure
                    else:
                        settled = current.complete(at=at)
                        await _document_queries.replace_document_snapshot(
                            session, model=model, document=settled
                        )
                        return ProcessingResult(ProcessingOutcome.SUCCESS)
                if failure is not None:
                    settled = current.fail(
                        at=at, code=failure.code, safe_message=failure.safe_message
                    )
                    result = ProcessingResult(
                        ProcessingOutcome.TERMINAL_FINALIZED, failure
                    )
                else:
                    raise DocumentConflictError("Document persistence conflict")
                await _document_queries.replace_document_snapshot(
                    session, model=model, document=settled
                )
                return result
        except SQLAlchemyError as exc:
            raise DocumentPersistenceError("Document persistence failed") from exc
