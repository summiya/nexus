"""Create an explicit generation under a short tenant-owned File lock."""

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.documents.domain import Document, DocumentStatus
from nexus.documents.ports.reprocessing import (
    DocumentReprocessing,
    DocumentReprocessingConflictError,
    DocumentReprocessingError,
)
from nexus.files.domain import FileStorageStatus
from nexus.infrastructure.persistence import _document_initiation_queries as queries
from nexus.infrastructure.persistence.document import _settle_cancelled_transaction
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.document_processing_request import (
    DocumentProcessingRequest,
)
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization


class SqlAlchemyDocumentReprocessing(DocumentReprocessing):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def create_generation(
        self,
        *,
        organization_public_id: UUID,
        source_file_public_id: UUID,
        expected_document_public_id: UUID,
        at: datetime,
    ) -> Document:
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Reprocessing requires an aware timestamp")
        transaction = asyncio.create_task(
            self._create(
                organization_public_id,
                source_file_public_id,
                expected_document_public_id,
                at,
            )
        )
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _create(
        self,
        organization_public_id: UUID,
        source_file_public_id: UUID,
        expected_document_public_id: UUID,
        at: datetime,
    ) -> Document:
        try:
            async with self._sessions.begin() as session:
                file = await session.scalar(
                    select(FileModel)
                    .join(Organization, Organization.id == FileModel.organization_id)
                    .where(
                        Organization.public_id == organization_public_id,
                        FileModel.public_id == source_file_public_id,
                    )
                    .with_for_update(of=FileModel)
                )
                if (
                    file is None
                    or file.storage_status != FileStorageStatus.AVAILABLE.value
                ):
                    raise DocumentReprocessingConflictError(
                        "Document reprocessing conflicts"
                    )
                latest = await session.scalar(
                    select(DocumentModel)
                    .where(
                        DocumentModel.source_file_id == file.id,
                        DocumentModel.organization_id == file.organization_id,
                    )
                    .order_by(DocumentModel.id.desc())
                    .limit(1)
                )
                active = await session.scalar(
                    select(DocumentModel.id)
                    .where(
                        DocumentModel.source_file_id == file.id,
                        DocumentModel.status.in_(
                            (
                                DocumentStatus.QUEUED.value,
                                DocumentStatus.PROCESSING.value,
                            )
                        ),
                    )
                    .limit(1)
                )
                if (
                    latest is None
                    or latest.public_id != expected_document_public_id
                    or latest.status
                    not in (DocumentStatus.COMPLETED.value, DocumentStatus.FAILED.value)
                    or active is not None
                    or at < latest.created_at
                ):
                    raise DocumentReprocessingConflictError(
                        "Document reprocessing conflicts"
                    )
                request = await session.scalar(
                    select(DocumentProcessingRequest).where(
                        DocumentProcessingRequest.document_id == latest.id,
                        DocumentProcessingRequest.organization_id
                        == file.organization_id,
                        DocumentProcessingRequest.source_file_id == file.id,
                    )
                )
                if (
                    request is None
                    or not request.source_entity_tag.strip()
                    or request.expected_size_bytes != file.size_bytes
                ):
                    raise DocumentReprocessingConflictError(
                        "Document reprocessing conflicts"
                    )
                document = Document(
                    public_id=uuid4(),
                    organization_public_id=organization_public_id,
                    source_file_public_id=source_file_public_id,
                    created_at=at,
                )
                await queries.insert_document_and_request(
                    session,
                    document=document,
                    source_entity_tag=request.source_entity_tag,
                    expected_size_bytes=request.expected_size_bytes,
                    at=at,
                )
                return document
        except SQLAlchemyError as exc:
            raise DocumentReprocessingError("Document reprocessing failed") from exc
