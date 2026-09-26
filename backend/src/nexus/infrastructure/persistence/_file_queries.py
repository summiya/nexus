"""Private SQLAlchemy queries for File persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import FileReferenceError
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User


async def insert_file(session: AsyncSession, file: File) -> None:
    await _insert_file(session, file)


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
    return _to_file(model, stored_organization_public_id, creator_public_id)


async def list_files(
    session: AsyncSession,
    *,
    organization_public_id: UUID,
    before_created_at: datetime | None,
    before_public_id: UUID | None,
    limit: int,
) -> tuple[File, ...]:
    """Return one newest-first tenant-scoped keyset page."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    if (before_created_at is None) != (before_public_id is None):
        raise ValueError("File pagination cursor must be complete")

    statement = (
        select(FileModel, Organization.public_id, User.public_id)
        .join(Organization, FileModel.organization_id == Organization.id)
        .join(
            User,
            (User.id == FileModel.created_by_user_id)
            & (User.organization_id == FileModel.organization_id),
        )
        .where(Organization.public_id == organization_public_id)
    )
    if before_created_at is not None and before_public_id is not None:
        statement = statement.where(
            tuple_(FileModel.created_at, FileModel.public_id)
            < tuple_(before_created_at, before_public_id)
        )

    rows = (
        await session.execute(
            statement.order_by(
                FileModel.created_at.desc(),
                FileModel.public_id.desc(),
            ).limit(limit)
        )
    ).all()
    return tuple(
        _to_file(model, stored_organization_public_id, creator_public_id)
        for model, stored_organization_public_id, creator_public_id in rows
    )


async def files_matching_identity(
    session: AsyncSession,
    *,
    file_public_id: UUID,
    storage_key: str,
) -> tuple[File, ...]:
    """Return File rows matching either immutable completion identity."""
    rows = (
        await session.execute(
            select(FileModel, Organization.public_id, User.public_id)
            .join(Organization, FileModel.organization_id == Organization.id)
            .join(
                User,
                (User.id == FileModel.created_by_user_id)
                & (User.organization_id == FileModel.organization_id),
            )
            .where(
                or_(
                    FileModel.public_id == file_public_id,
                    FileModel.storage_key == storage_key,
                )
            )
        )
    ).all()
    return tuple(
        _to_file(model, organization_public_id, creator_public_id)
        for model, organization_public_id, creator_public_id in rows
    )


def _to_file(
    model: FileModel,
    organization_public_id: UUID,
    creator_public_id: UUID,
) -> File:
    return File(
        public_id=model.public_id,
        organization_public_id=organization_public_id,
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


async def file_storage_status_for_update(
    session: AsyncSession,
    *,
    storage_key: str,
) -> FileStorageStatus | None:
    """Lock one File by storage key and return its current lifecycle status."""
    value = (
        await session.execute(
            select(FileModel.storage_status)
            .where(FileModel.storage_key == storage_key)
            .with_for_update()
        )
    ).scalar_one_or_none()
    return FileStorageStatus(value) if value is not None else None


async def update_file_storage_status(
    session: AsyncSession,
    *,
    storage_key: str,
    target_status: FileStorageStatus,
    updated_at: datetime,
) -> None:
    """Update one already-locked File lifecycle status."""
    await session.execute(
        update(FileModel)
        .where(FileModel.storage_key == storage_key)
        .values(
            storage_status=target_status.value,
            updated_at=updated_at,
        )
    )
