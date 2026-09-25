"""Private SQLAlchemy queries for File persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.files.domain import File, FileStorageStatus, FileUploadAttempt
from nexus.files.ports import FileReferenceError
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.file_upload_attempt import (
    FileUploadAttempt as FileUploadAttemptModel,
)
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User


async def insert_file(session: AsyncSession, file: File) -> None:
    await _insert_file(session, file)


async def insert_pending_upload(
    session: AsyncSession,
    *,
    file: File,
    upload_attempt: FileUploadAttempt,
) -> None:
    if (
        upload_attempt.file_public_id != file.public_id
        or upload_attempt.organization_public_id != file.organization_public_id
    ):
        raise FileReferenceError("File upload attempt does not match File")

    model = await _insert_file(session, file)
    session.add(
        FileUploadAttemptModel(
            file_id=model.id,
            organization_id=model.organization_id,
            declared_size_bytes=upload_attempt.declared_size_bytes,
            grant_expires_at=upload_attempt.grant_expires_at,
            created_at=upload_attempt.created_at,
        )
    )
    await session.flush()


async def _insert_file(session: AsyncSession, file: File) -> FileModel:
    reference = (
        await session.execute(
            select(Organization.id, User.id)
            .join(User, User.organization_id == Organization.id)
            .where(
                Organization.public_id == file.organization_public_id,
                User.public_id == file.created_by_user_public_id,
            )
        )
    ).one_or_none()
    if reference is None:
        raise FileReferenceError("File organization or creator was not found")

    organization_id, creator_id = reference
    model = FileModel(
        public_id=file.public_id,
        organization_id=organization_id,
        created_by_user_id=creator_id,
        original_name=file.original_name,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        storage_key=file.storage_key,
        storage_status=file.storage_status.value,
        checksum_sha256=file.checksum_sha256,
        created_at=file.created_at,
        updated_at=file.updated_at,
    )
    session.add(model)
    await session.flush()
    return model


async def get_file(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    file_public_id: UUID,
) -> File | None:
    row = (
        await session.execute(
            select(FileModel, Organization.public_id, User.public_id)
            .join(Organization, FileModel.organization_id == Organization.id)
            .join(
                User,
                (User.id == FileModel.created_by_user_id)
                & (User.organization_id == FileModel.organization_id),
            )
            .where(
                Organization.public_id == organization_public_id,
                FileModel.public_id == file_public_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None

    model, stored_organization_public_id, creator_public_id = row
    return File(
        public_id=model.public_id,
        organization_public_id=stored_organization_public_id,
        created_by_user_public_id=creator_public_id,
        original_name=model.original_name,
        mime_type=model.mime_type,
        size_bytes=model.size_bytes,
        storage_key=model.storage_key,
        storage_status=FileStorageStatus(model.storage_status),
        checksum_sha256=model.checksum_sha256,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
