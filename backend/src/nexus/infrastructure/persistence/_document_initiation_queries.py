"""Private queries for atomic File-to-Document initiation."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.documents.domain import Document
from nexus.files.domain import File
from nexus.infrastructure.persistence import _document_queries
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.document_processing_request import (
    DocumentProcessingRequest,
)
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization


async def request_for_file(
    session: AsyncSession, file: File
) -> DocumentProcessingRequest | None:
    return await session.scalar(
        select(DocumentProcessingRequest)
        .join(
            FileModel,
            (FileModel.id == DocumentProcessingRequest.source_file_id)
            & (FileModel.organization_id == DocumentProcessingRequest.organization_id),
        )
        .join(Organization, Organization.id == FileModel.organization_id)
        .where(
            FileModel.public_id == file.public_id,
            Organization.public_id == file.organization_public_id,
        )
        .order_by(DocumentProcessingRequest.id)
        .limit(1)
    )


async def has_document(session: AsyncSession, file: File) -> bool:
    return (
        await session.scalar(
            select(DocumentModel.id)
            .join(
                FileModel,
                (FileModel.id == DocumentModel.source_file_id)
                & (FileModel.organization_id == DocumentModel.organization_id),
            )
            .join(Organization, Organization.id == FileModel.organization_id)
            .where(
                FileModel.public_id == file.public_id,
                Organization.public_id == file.organization_public_id,
            )
            .limit(1)
        )
        is not None
    )


async def insert_document_and_request(
    session: AsyncSession,
    *,
    document: Document,
    source_entity_tag: str,
    expected_size_bytes: int,
    at: datetime,
) -> None:
    await _document_queries.insert_document(session, document)
    model = (
        await session.execute(
            select(DocumentModel)
            .join(Organization, Organization.id == DocumentModel.organization_id)
            .where(
                DocumentModel.public_id == document.public_id,
                Organization.public_id == document.organization_public_id,
            )
        )
    ).scalar_one()
    session.add(
        DocumentProcessingRequest(
            public_id=uuid4(),
            organization_id=model.organization_id,
            source_file_id=model.source_file_id,
            document_id=model.id,
            source_entity_tag=source_entity_tag,
            expected_size_bytes=expected_size_bytes,
            created_at=at,
        )
    )
    await session.flush()
