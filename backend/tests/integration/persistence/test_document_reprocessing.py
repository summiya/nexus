import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from tests.integration.persistence.test_document_initiation import (
    NOW,
    _scan,
    _seed_file,
)

from nexus.documents.domain import DocumentStatus
from nexus.documents.ports.reprocessing import DocumentReprocessingConflictError
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_reprocessing import (
    SqlAlchemyDocumentReprocessing,
)
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.document_processing_request import (
    DocumentProcessingRequest,
)


@pytest.fixture
def migrated_engine(migrated_database):
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


async def seed_terminal(engine, sessions):
    file = _seed_file(engine)
    await _scan(sessions, file)
    with Session(engine) as session:
        identity = session.scalar(select(DocumentModel.public_id))
    persistence = SqlAlchemyDocumentPersistence(sessions)
    document = await persistence.get_document(
        organization_public_id=file.organization_public_id, document_public_id=identity
    )
    started = document.start_processing(at=NOW, processing_version="old")
    await persistence.update_document(expected=document, document=started)
    terminal = started.fail(at=NOW, code="TEST", safe_message="safe")
    await persistence.update_document(expected=started, document=terminal)
    return file, terminal


async def reprocess(adapter, file, expected):
    return await adapter.create_generation(
        organization_public_id=file.organization_public_id,
        source_file_public_id=file.public_id,
        expected_document_public_id=expected.public_id,
        at=NOW + timedelta(days=1),
    )


def test_new_generation_preserves_history_and_initial_scan_duplicate(
    migrated_engine, persistence_async_session_factory
):
    async def run():
        file, terminal = await seed_terminal(
            migrated_engine, persistence_async_session_factory
        )
        adapter = SqlAlchemyDocumentReprocessing(persistence_async_session_factory)
        generation = await reprocess(adapter, file, terminal)
        assert generation.status is DocumentStatus.QUEUED
        assert (
            generation.public_id != terminal.public_id
            and generation.processing_version is None
        )
        stored = await SqlAlchemyDocumentPersistence(
            persistence_async_session_factory
        ).get_document(
            organization_public_id=file.organization_public_id,
            document_public_id=terminal.public_id,
        )
        assert stored == terminal
        await _scan(persistence_async_session_factory, file)
        with Session(migrated_engine) as session:
            requests = list(
                session.scalars(
                    select(DocumentProcessingRequest).order_by(
                        DocumentProcessingRequest.id
                    )
                )
            )
            assert len(requests) == 2
            assert requests[0].public_id != requests[1].public_id
            assert (
                requests[0].source_entity_tag
                == requests[1].source_entity_tag
                == "verified-v1"
            )
            assert (
                requests[0].expected_size_bytes == requests[1].expected_size_bytes == 42
            )

    asyncio.run(run())


def test_concurrent_reprocess_creates_at_most_one_active_generation(
    migrated_engine, persistence_async_session_factory
):
    async def run():
        file, terminal = await seed_terminal(
            migrated_engine, persistence_async_session_factory
        )
        adapter = SqlAlchemyDocumentReprocessing(persistence_async_session_factory)
        results = await asyncio.gather(
            reprocess(adapter, file, terminal),
            reprocess(adapter, file, terminal),
            return_exceptions=True,
        )
        assert (
            sum(isinstance(r, DocumentReprocessingConflictError) for r in results) == 1
        )
        with Session(migrated_engine) as session:
            assert len(list(session.scalars(select(DocumentProcessingRequest)))) == 2

    asyncio.run(run())


def test_latest_generation_uses_its_exact_request_and_rejects_stale_expected(
    migrated_engine, persistence_async_session_factory
):
    async def run():
        file, first = await seed_terminal(
            migrated_engine, persistence_async_session_factory
        )
        adapter = SqlAlchemyDocumentReprocessing(persistence_async_session_factory)
        second = await reprocess(adapter, file, first)
        persistence = SqlAlchemyDocumentPersistence(persistence_async_session_factory)
        started = second.start_processing(
            at=NOW + timedelta(days=1), processing_version="new"
        )
        await persistence.update_document(expected=second, document=started)
        terminal = started.fail(
            at=NOW + timedelta(days=1), code="TEST", safe_message="safe"
        )
        await persistence.update_document(expected=started, document=terminal)
        with Session(migrated_engine) as session:
            model = session.scalar(
                select(DocumentModel).where(DocumentModel.public_id == second.public_id)
            )
            session.execute(
                update(DocumentProcessingRequest)
                .where(DocumentProcessingRequest.document_id == model.id)
                .values(source_entity_tag="trusted-second")
            )
            session.commit()
        with pytest.raises(DocumentReprocessingConflictError):
            await reprocess(adapter, file, first)
        await reprocess(adapter, file, terminal)
        with Session(migrated_engine) as session:
            latest = session.scalar(
                select(DocumentProcessingRequest)
                .order_by(DocumentProcessingRequest.id.desc())
                .limit(1)
            )
            assert latest.source_entity_tag == "trusted-second"

    asyncio.run(run())


def test_foreign_and_missing_reprocessing_share_conflict_and_do_not_mutate(
    migrated_engine, persistence_async_session_factory
):
    async def run():
        file, terminal = await seed_terminal(
            migrated_engine, persistence_async_session_factory
        )
        adapter = SqlAlchemyDocumentReprocessing(persistence_async_session_factory)
        for org, identity in [
            (uuid4(), file.public_id),
            (file.organization_public_id, uuid4()),
        ]:
            with pytest.raises(DocumentReprocessingConflictError):
                await adapter.create_generation(
                    organization_public_id=org,
                    source_file_public_id=identity,
                    expected_document_public_id=terminal.public_id,
                    at=NOW,
                )
        with Session(migrated_engine) as session:
            assert len(list(session.scalars(select(DocumentProcessingRequest)))) == 1

    asyncio.run(run())


def test_downgrade_refuses_to_delete_generation_history(
    migrated_database, persistence_async_session_factory
):
    config, engine = migrated_database
    command.upgrade(config, "head")

    async def run():
        file, terminal = await seed_terminal(engine, persistence_async_session_factory)
        await reprocess(
            SqlAlchemyDocumentReprocessing(persistence_async_session_factory),
            file,
            terminal,
        )

    asyncio.run(run())
    with pytest.raises(RuntimeError, match="generation history"):
        command.downgrade(config, "20261007_0018")
    with Session(engine) as session:
        assert len(list(session.scalars(select(DocumentProcessingRequest)))) == 2


def test_single_generation_migration_round_trip_keeps_constraints(
    migrated_database, persistence_async_session_factory
):
    from sqlalchemy import inspect

    config, engine = migrated_database
    command.upgrade(config, "head")
    asyncio.run(seed_terminal(engine, persistence_async_session_factory))
    command.downgrade(config, "20261007_0018")
    constraints = inspect(engine).get_unique_constraints("document_processing_requests")
    assert "uq_document_requests_initial_file" in {
        constraint["name"] for constraint in constraints
    }
    command.upgrade(config, "head")
    constraints = inspect(engine).get_unique_constraints("document_processing_requests")
    assert {"uq_document_requests_public_id", "uq_document_requests_document"} <= {
        constraint["name"] for constraint in constraints
    }
    assert "uq_document_requests_initial_file" not in {
        constraint["name"] for constraint in constraints
    }
    assert any(
        index["column_names"] == ["source_file_id", "id"]
        for index in inspect(engine).get_indexes("document_processing_requests")
    )


@pytest.mark.parametrize("conflict", ["size", "unavailable", "missing_request"])
def test_reprocessing_revalidates_file_and_exact_request(
    migrated_engine, persistence_async_session_factory, conflict
):
    from sqlalchemy import delete

    from nexus.infrastructure.persistence.models.file import File as FileModel

    async def run():
        file, terminal = await seed_terminal(
            migrated_engine, persistence_async_session_factory
        )
        with Session(migrated_engine) as session:
            if conflict == "size":
                session.execute(update(FileModel).values(size_bytes=43))
            if conflict == "unavailable":
                session.execute(update(FileModel).values(storage_status="deleting"))
            if conflict == "missing_request":
                session.execute(delete(DocumentProcessingRequest))
            session.commit()
        with pytest.raises(DocumentReprocessingConflictError):
            await reprocess(
                SqlAlchemyDocumentReprocessing(persistence_async_session_factory),
                file,
                terminal,
            )
        with Session(migrated_engine) as session:
            assert len(list(session.scalars(select(DocumentModel)))) == 1

    asyncio.run(run())
