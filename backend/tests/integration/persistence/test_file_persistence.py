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

from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import FilePersistenceError, FileReferenceError
from nexus.infrastructure.persistence import _file_queries as queries
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User

TIMESTAMP = datetime(2026, 9, 24, tzinfo=UTC)


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
            name="File Organization",
            slug=f"files-{uuid4().hex[:12]}",
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
        storage_key=f"file-key-{uuid4()}",
        storage_status=FileStorageStatus.AVAILABLE,
        checksum_sha256=None,
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    return replace(file, **changes)


def _persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyFilePersistence:
    return SqlAlchemyFilePersistence(session_factory)


def test_create_and_get_file_maps_domain_without_internal_id(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    file = _file(organization_public_id, user_public_id)
    persistence = _persistence(persistence_async_session_factory)

    asyncio.run(persistence.create_file(file))
    stored = asyncio.run(
        persistence.get_file(
            organization_public_id=organization_public_id,
            file_public_id=file.public_id,
        )
    )

    assert stored == file
    assert isinstance(stored, File)
    assert not hasattr(stored, "id")
    assert stored.checksum_sha256 is None


def test_file_optional_checksum_and_pending_metadata_round_trip(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    file = _file(
        organization_public_id,
        user_public_id,
        size_bytes=None,
        storage_status=FileStorageStatus.PENDING,
        checksum_sha256="a" * 64,
    )
    persistence = _persistence(persistence_async_session_factory)

    asyncio.run(persistence.create_file(file))
    stored = asyncio.run(
        persistence.get_file(
            organization_public_id=organization_public_id,
            file_public_id=file.public_id,
        )
    )

    assert stored == file


def test_get_file_hides_file_from_another_organization(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    other_organization_public_id, _ = _seed_identity(migrated_engine)
    file = _file(organization_public_id, user_public_id)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_file(file))

    stored = asyncio.run(
        persistence.get_file(
            organization_public_id=other_organization_public_id,
            file_public_id=file.public_id,
        )
    )

    assert stored is None


def test_get_file_returns_none_for_unknown_file(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, _ = _seed_identity(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)

    stored = asyncio.run(
        persistence.get_file(
            organization_public_id=organization_public_id,
            file_public_id=uuid4(),
        )
    )

    assert stored is None


def test_create_file_rejects_creator_from_another_organization(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, _ = _seed_identity(migrated_engine)
    _, other_user_public_id = _seed_identity(migrated_engine)
    file = _file(organization_public_id, other_user_public_id)
    persistence = _persistence(persistence_async_session_factory)

    with pytest.raises(FileReferenceError):
        asyncio.run(persistence.create_file(file))

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(FileModel).where(FileModel.public_id == file.public_id)
            )
            is None
        )


def test_create_file_translates_unexpected_integrity_failure(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    file = _file(organization_public_id, user_public_id)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_file(file))

    with pytest.raises(FilePersistenceError):
        asyncio.run(
            persistence.create_file(
                replace(file, storage_key=f"different-key-{uuid4()}")
            )
        )


def test_create_file_transaction_settles_before_cancellation_propagates(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_public_id, user_public_id = _seed_identity(migrated_engine)
    file = _file(organization_public_id, user_public_id)
    transaction_started = asyncio.Event()
    allow_transaction_to_finish = asyncio.Event()
    original_insert = queries.insert_file

    async def delayed_insert(
        session: AsyncSession,
        file: File,
    ) -> None:
        await original_insert(session, file)
        transaction_started.set()
        await allow_transaction_to_finish.wait()

    monkeypatch.setattr(queries, "insert_file", delayed_insert)

    async def scenario() -> None:
        operation = asyncio.create_task(
            _persistence(persistence_async_session_factory).create_file(file)
        )
        await transaction_started.wait()
        operation.cancel()
        await asyncio.sleep(0)
        assert operation.done() is False
        allow_transaction_to_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await operation

    asyncio.run(scenario())

    with Session(migrated_engine) as session:
        stored_file = session.scalar(
            select(FileModel).where(FileModel.public_id == file.public_id)
        )
        assert stored_file is not None
