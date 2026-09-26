from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.files.application import VerifyUploadCompletion
from nexus.files.domain import File, FileStorageStatus, UploadContext
from nexus.files.ports import (
    FileIdentityConflictError,
    FilePersistenceError,
    FileReferenceError,
    StoredObjectProperties,
    UploadCompletionEvent,
)
from nexus.infrastructure.persistence import _file_queries as queries
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.upload_context import AesGcmUploadContextProtector

TIMESTAMP = datetime(2026, 9, 26, tzinfo=UTC)
CONTEXT_KEY = b"nexus-development-upload-key-001"


class _VerifiedStorage:
    def __init__(self, properties: StoredObjectProperties) -> None:
        self.properties = properties

    async def get_object_properties(
        self,
        *,
        storage_key: str,
    ) -> StoredObjectProperties:
        del storage_key
        return self.properties


@pytest.fixture
def migrated_engine(migrated_database: tuple[Config, Engine]) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def _seed_identity(engine: Engine) -> tuple[UUID, UUID]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Completion Organization",
            slug=f"completion-{uuid4().hex[:12]}",
            status="active",
        )
        session.add(
            User(
                public_id=user_public_id,
                organization=organization,
                email=f"{uuid4().hex}@example.com",
                status="active",
            )
        )
        session.commit()
    return organization_public_id, user_public_id


def _file(
    organization_public_id: UUID,
    user_public_id: UUID,
    **changes: object,
) -> File:
    file = File(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        created_by_user_public_id=user_public_id,
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=42,
        storage_key=f"files/{uuid4().hex}",
        storage_status=FileStorageStatus.PENDING,
        checksum_sha256=None,
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    return replace(file, **changes)


def _persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyFilePersistence:
    return SqlAlchemyFilePersistence(session_factory)


def _stored_rows(engine: Engine) -> list[FileModel]:
    with Session(engine) as session:
        return list(session.scalars(select(FileModel)).all())


def test_verified_completion_creates_one_file_and_redelivery_is_idempotent(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id = _seed_identity(migrated_engine)
    storage_key = f"files/{uuid4().hex}"
    context = UploadContext(
        version=1,
        file_public_id=uuid4(),
        organization_public_id=organization_id,
        created_by_user_public_id=user_id,
        storage_key=storage_key,
        original_name="report.pdf",
        mime_type="application/pdf",
        declared_size_bytes=42,
        issued_at=TIMESTAMP,
        grant_expires_at=TIMESTAMP.replace(minute=10),
    )
    protector = AesGcmUploadContextProtector(CONTEXT_KEY)
    properties = StoredObjectProperties(
        entity_tag="0x8D123",
        size_bytes=42,
        metadata={"nexus_upload_context": protector.protect(context)},
    )
    handler = VerifyUploadCompletion(
        object_storage=_VerifiedStorage(properties),  # type: ignore[arg-type]
        context_protector=protector,
        persistence=_persistence(persistence_async_session_factory),
        max_size_bytes=536_870_912,
        clock=lambda: TIMESTAMP,
    )
    event = UploadCompletionEvent(
        event_id="event-1",
        source="azure-primary",
        storage_key=storage_key,
        occurred_at=TIMESTAMP,
        entity_tag="0x8D123",
        reported_size_bytes=42,
    )

    asyncio.run(handler.handle(event))
    asyncio.run(handler.handle(event))

    rows = _stored_rows(migrated_engine)
    assert len(rows) == 1
    assert rows[0].public_id == context.file_public_id
    assert rows[0].storage_status == FileStorageStatus.PENDING.value
    assert rows[0].size_bytes == 42


def test_new_and_duplicate_completion_register_exactly_one_pending_file(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id = _seed_identity(migrated_engine)
    file = _file(organization_id, user_id)
    persistence = _persistence(persistence_async_session_factory)

    asyncio.run(persistence.register_completed_upload(file))
    asyncio.run(persistence.register_completed_upload(file))

    rows = _stored_rows(migrated_engine)
    assert len(rows) == 1
    assert rows[0].public_id == file.public_id
    assert rows[0].storage_key == file.storage_key
    assert rows[0].storage_status == FileStorageStatus.PENDING.value
    assert rows[0].size_bytes == 42


@pytest.mark.parametrize("conflict", ["public_id", "storage_key", "ownership"])
def test_partial_identity_or_ownership_match_is_rejected(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    conflict: str,
) -> None:
    organization_id, user_id = _seed_identity(migrated_engine)
    other_organization_id, other_user_id = _seed_identity(migrated_engine)
    existing = _file(organization_id, user_id)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_file(existing))

    if conflict == "public_id":
        candidate = replace(existing, storage_key=f"files/{uuid4().hex}")
    elif conflict == "storage_key":
        candidate = replace(existing, public_id=uuid4())
    else:
        candidate = replace(
            existing,
            organization_public_id=other_organization_id,
            created_by_user_public_id=other_user_id,
        )

    with pytest.raises(FileIdentityConflictError):
        asyncio.run(persistence.register_completed_upload(candidate))

    assert len(_stored_rows(migrated_engine)) == 1


def test_divergent_identities_are_rejected(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id = _seed_identity(migrated_engine)
    first = _file(organization_id, user_id)
    second = _file(organization_id, user_id)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_file(first))
    asyncio.run(persistence.create_file(second))
    candidate = replace(first, storage_key=second.storage_key)

    with pytest.raises(FileIdentityConflictError):
        asyncio.run(persistence.register_completed_upload(candidate))

    assert len(_stored_rows(migrated_engine)) == 2


def test_invalid_creator_organization_relationship_is_rejected(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, _user_id = _seed_identity(migrated_engine)
    _other_organization_id, other_user_id = _seed_identity(migrated_engine)

    with pytest.raises(FileReferenceError):
        asyncio.run(
            _persistence(persistence_async_session_factory).register_completed_upload(
                _file(organization_id, other_user_id)
            )
        )

    assert _stored_rows(migrated_engine) == []


def test_concurrent_exact_registration_rechecks_after_unique_race(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id, user_id = _seed_identity(migrated_engine)
    file = _file(organization_id, user_id)
    persistence = _persistence(persistence_async_session_factory)
    insert_count = 0
    both_ready = asyncio.Event()
    original_insert = queries.insert_file

    async def synchronized_insert(session: AsyncSession, candidate: File) -> None:
        nonlocal insert_count
        insert_count += 1
        if insert_count == 2:
            both_ready.set()
        await both_ready.wait()
        await original_insert(session, candidate)

    monkeypatch.setattr(queries, "insert_file", synchronized_insert)

    async def scenario() -> None:
        await asyncio.gather(
            persistence.register_completed_upload(file),
            persistence.register_completed_upload(file),
        )

    asyncio.run(scenario())

    assert insert_count == 2
    assert len(_stored_rows(migrated_engine)) == 1


def test_unrelated_database_integrity_failure_is_not_duplicate_success(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id, user_id = _seed_identity(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)

    async def invalid_insert(session: AsyncSession, file: File) -> None:
        del file
        session.add(
            FileModel(
                public_id=uuid4(),
                organization_id=-1,
                created_by_user_id=-1,
                original_name="invalid",
                mime_type="application/octet-stream",
                size_bytes=1,
                storage_key=f"files/{uuid4().hex}",
                storage_status="invalid",
                checksum_sha256=None,
                created_at=TIMESTAMP,
                updated_at=TIMESTAMP,
            )
        )
        await session.flush()

    monkeypatch.setattr(queries, "insert_file", invalid_insert)

    with pytest.raises(FilePersistenceError):
        asyncio.run(
            persistence.register_completed_upload(_file(organization_id, user_id))
        )

    assert _stored_rows(migrated_engine) == []
