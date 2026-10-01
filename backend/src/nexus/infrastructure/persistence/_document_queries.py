"""Private SQLAlchemy queries for Document persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.documents.domain import Document, DocumentFailure, DocumentStatus
from nexus.documents.ports import DocumentReferenceError
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization


async def insert_document(session: AsyncSession, document: Document) -> None:
    reference = (
        await session.execute(
            select(Organization.id, FileModel.id)
            .join(FileModel, FileModel.organization_id == Organization.id)
            .where(
                Organization.public_id == document.organization_public_id,
                FileModel.public_id == document.source_file_public_id,
            )
        )
    ).one_or_none()
    if reference is None:
        raise DocumentReferenceError(
            "Document organization or source File was not found"
        )

    organization_id, source_file_id = reference
    session.add(
        DocumentModel(
            public_id=document.public_id,
            organization_id=organization_id,
            source_file_id=source_file_id,
            **_snapshot_values(document),
        )
    )
    await session.flush()


async def get_document(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    document_public_id: UUID,
) -> Document | None:
    row = await _document_row(
        session,
        organization_public_id=organization_public_id,
        document_public_id=document_public_id,
        for_update=False,
    )
    if row is None:
        return None
    model, stored_organization_public_id, source_file_public_id = row
    return _to_document(
        model,
        stored_organization_public_id,
        source_file_public_id,
    )


async def document_for_update(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    document_public_id: UUID,
) -> tuple[DocumentModel, Document] | None:
    row = await _document_row(
        session,
        organization_public_id=organization_public_id,
        document_public_id=document_public_id,
        for_update=True,
    )
    if row is None:
        return None
    model, stored_organization_public_id, source_file_public_id = row
    return (
        model,
        _to_document(
            model,
            stored_organization_public_id,
            source_file_public_id,
        ),
    )


async def replace_document_snapshot(
    session: AsyncSession,
    *,
    model: DocumentModel,
    document: Document,
) -> None:
    for name, value in _snapshot_values(document).items():
        setattr(model, name, value)
    await session.flush()


async def _document_row(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    document_public_id: UUID,
    for_update: bool,
) -> tuple[DocumentModel, UUID, UUID] | None:
    statement = (
        select(DocumentModel, Organization.public_id, FileModel.public_id)
        .join(Organization, DocumentModel.organization_id == Organization.id)
        .join(
            FileModel,
            (FileModel.id == DocumentModel.source_file_id)
            & (FileModel.organization_id == DocumentModel.organization_id),
        )
        .where(
            Organization.public_id == organization_public_id,
            DocumentModel.public_id == document_public_id,
        )
    )
    if for_update:
        statement = statement.with_for_update(of=DocumentModel)
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    model, stored_organization_public_id, source_file_public_id = row
    return model, stored_organization_public_id, source_file_public_id


def _snapshot_values(document: Document) -> dict[str, object]:
    return {
        "status": document.status.value,
        "processing_version": document.processing_version,
        "extractor_version": document.extractor_version,
        "processing_started_at": document.processing_started_at,
        "processing_completed_at": document.processing_completed_at,
        "failed_at": document.failed_at,
        "failure_code": document.failure.code if document.failure else None,
        "failure_safe_message": (
            document.failure.safe_message if document.failure else None
        ),
        "created_at": document.created_at,
    }


def _to_document(
    model: DocumentModel,
    organization_public_id: UUID,
    source_file_public_id: UUID,
) -> Document:
    failure = None
    if model.failure_code is not None and model.failure_safe_message is not None:
        failure = DocumentFailure(
            code=model.failure_code,
            safe_message=model.failure_safe_message,
        )
    return Document(
        public_id=model.public_id,
        organization_public_id=organization_public_id,
        source_file_public_id=source_file_public_id,
        created_at=model.created_at,
        status=DocumentStatus(model.status),
        processing_version=model.processing_version,
        extractor_version=model.extractor_version,
        processing_started_at=model.processing_started_at,
        processing_completed_at=model.processing_completed_at,
        failed_at=model.failed_at,
        failure=failure,
    )
