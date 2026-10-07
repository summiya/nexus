from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.documents.domain import Document
from nexus.documents.ports.initiation import (
    DocumentInitiationConflictError,
    DocumentInitiationError,
)
from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import FileReferencedError
from nexus.infrastructure.persistence import _document_initiation_queries as queries
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_initiation import (
    SqlAlchemyDocumentInitiationPersistence,
)
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence
from nexus.infrastructure.persistence.models import Document as DocumentModel
from nexus.infrastructure.persistence.models import (
    DocumentProcessingRequest,
    Organization,
    User,
)
from nexus.infrastructure.persistence.models import File as FileModel

NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def migrated_engine(migrated_database: tuple[Config, Engine]) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def _seed_file(
    engine: Engine, *, status: str = "pending", name: str = "report.pdf"
) -> File:
    with Session(engine) as session:
        org = Organization(
            public_id=uuid4(), name="Initiation", slug=uuid4().hex, status="active"
        )
        user = User(
            public_id=uuid4(),
            organization=org,
            email=f"{uuid4().hex}@example.com",
            status="active",
        )
        session.add(user)
        session.flush()
        model = FileModel(
            public_id=uuid4(),
            organization_id=org.id,
            created_by_user_id=user.id,
            original_name=name,
            mime_type="application/pdf",
            size_bytes=42,
            storage_key=f"files/{uuid4().hex}",
            storage_status=status,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(model)
        session.flush()
        file = File(
            public_id=model.public_id,
            organization_public_id=org.public_id,
            created_by_user_public_id=user.public_id,
            original_name=name,
            mime_type=model.mime_type,
            size_bytes=42,
            storage_key=model.storage_key,
            storage_status=FileStorageStatus(status),
            checksum_sha256=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.commit()
        return file


def _scan(
    factory: async_sessionmaker[AsyncSession],
    file: File,
    *,
    tag: str = "verified-v1",
    size: int = 42,
):
    return SqlAlchemyDocumentInitiationPersistence(factory).apply_clean_scan(
        storage_key=file.storage_key,
        source_entity_tag=tag,
        expected_size_bytes=size,
        at=NOW,
    )


def _rows(engine: Engine):
    with Session(engine) as session:
        return (
            list(session.scalars(select(FileModel)).all()),
            list(session.scalars(select(DocumentModel)).all()),
            list(session.scalars(select(DocumentProcessingRequest)).all()),
        )


def test_clean_scan_commits_available_document_and_request_once(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))
    first = _rows(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))
    files, docs, requests = _rows(migrated_engine)
    assert len(files) == len(docs) == len(requests) == 1
    assert files[0].storage_status == "available"
    assert docs[0].status == "queued"
    assert docs[0].processing_version is None
    assert docs[0].extractor_version is None
    assert (
        docs[0].organization_id
        == files[0].organization_id
        == requests[0].organization_id
    )
    assert requests[0].source_file_id == docs[0].source_file_id == files[0].id
    assert requests[0].document_id == docs[0].id
    assert requests[0].source_entity_tag == "verified-v1"
    assert requests[0].expected_size_bytes == 42
    assert requests[0].dispatched_at is None
    assert requests[0].public_id == first[2][0].public_id
    assert docs[0].public_id == first[1][0].public_id
    assert "storage_key" not in DocumentProcessingRequest.__table__.c


@pytest.mark.parametrize("status", ["available", "deleting"])
def test_historical_available_and_deleting_do_not_initiate(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    status: str,
) -> None:
    file = _seed_file(migrated_engine, status=status)
    asyncio.run(_scan(persistence_async_session_factory, file))
    files, docs, requests = _rows(migrated_engine)
    assert files[0].storage_status == status
    assert docs == requests == []


def test_failed_file_rejects_clean_scan(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine, status="failed")
    with pytest.raises(DocumentInitiationConflictError):
        asyncio.run(_scan(persistence_async_session_factory, file))
    assert _rows(migrated_engine)[0][0].storage_status == "failed"
    assert _rows(migrated_engine)[1:] == ([], [])


def test_missing_file_is_retryable_without_disclosing_identity(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    with pytest.raises(DocumentInitiationError) as captured:
        asyncio.run(
            _scan(
                persistence_async_session_factory,
                replace(file, storage_key=f"files/{uuid4().hex}"),
            )
        )
    assert file.storage_key not in str(captured.value)
    assert _rows(migrated_engine)[1:] == ([], [])


def test_unsupported_file_becomes_available_without_ingestion(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine, name="report.xlsx")
    asyncio.run(_scan(persistence_async_session_factory, file))
    asyncio.run(_scan(persistence_async_session_factory, file))
    assert _rows(migrated_engine)[0][0].storage_status == "available"
    assert _rows(migrated_engine)[1:] == ([], [])


@pytest.mark.parametrize("duplicate", [False, True])
def test_source_size_conflict_leaves_state_unchanged(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    duplicate: bool,
) -> None:
    file = _seed_file(migrated_engine)
    if duplicate:
        asyncio.run(_scan(persistence_async_session_factory, file))
    with pytest.raises(DocumentInitiationConflictError):
        asyncio.run(_scan(persistence_async_session_factory, file, size=43))
    files, docs, requests = _rows(migrated_engine)
    assert files[0].storage_status == ("available" if duplicate else "pending")
    assert len(docs) == len(requests) == int(duplicate)
    if requests:
        assert requests[0].expected_size_bytes == 42


def test_duplicate_changed_version_does_not_replace_request(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))
    with pytest.raises(DocumentInitiationConflictError):
        asyncio.run(_scan(persistence_async_session_factory, file, tag="different-v2"))
    assert _rows(migrated_engine)[2][0].source_entity_tag == "verified-v1"


def test_request_failure_rolls_back_file_and_document_then_retry_succeeds(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = _seed_file(migrated_engine)
    original = queries.insert_document_and_request

    async def fail_after_insert(session: AsyncSession, **kwargs) -> None:
        await original(session, **kwargs)
        raise RuntimeError("injected crash before commit")

    with monkeypatch.context() as patch:
        patch.setattr(queries, "insert_document_and_request", fail_after_insert)
        with pytest.raises(RuntimeError):
            asyncio.run(_scan(persistence_async_session_factory, file))
    assert _rows(migrated_engine)[0][0].storage_status == "pending"
    assert _rows(migrated_engine)[1:] == ([], [])
    asyncio.run(_scan(persistence_async_session_factory, file))
    assert len(_rows(migrated_engine)[2]) == 1


def test_concurrent_clean_scans_create_one_initial_request(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)

    async def scenario() -> None:
        await asyncio.gather(
            *(_scan(persistence_async_session_factory, file) for _ in range(6))
        )

    asyncio.run(scenario())
    assert len(_rows(migrated_engine)[1]) == len(_rows(migrated_engine)[2]) == 1


def test_terminal_document_redelivery_does_not_reprocess(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))
    docs = SqlAlchemyDocumentPersistence(persistence_async_session_factory)

    async def scenario() -> None:
        queued = await docs.get_document(
            organization_public_id=file.organization_public_id,
            document_public_id=_rows(migrated_engine)[1][0].public_id,
        )
        assert queued is not None
        processing = queued.start_processing(at=NOW, processing_version="test-v1")
        await docs.update_document(expected=queued, document=processing)
        await docs.update_document(
            expected=processing,
            document=processing.fail(
                at=NOW, code="TEST_FAILURE", safe_message="Test failure"
            ),
        )
        await _scan(persistence_async_session_factory, file)

    asyncio.run(scenario())
    assert len(_rows(migrated_engine)[1]) == len(_rows(migrated_engine)[2]) == 1
    assert _rows(migrated_engine)[1][0].status == "failed"


def test_pending_file_with_existing_document_is_not_adopted(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    document = Document(
        public_id=uuid4(),
        organization_public_id=file.organization_public_id,
        source_file_public_id=file.public_id,
        created_at=NOW,
    )
    asyncio.run(
        SqlAlchemyDocumentPersistence(
            persistence_async_session_factory
        ).create_document(document)
    )
    with pytest.raises(DocumentInitiationConflictError):
        asyncio.run(_scan(persistence_async_session_factory, file))
    assert _rows(migrated_engine)[0][0].storage_status == "pending"
    assert _rows(migrated_engine)[2] == []


def test_cancellation_waits_for_atomic_commit(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = _seed_file(migrated_engine)
    ready, release = asyncio.Event(), asyncio.Event()
    original = queries.insert_document_and_request

    async def delayed(session: AsyncSession, **kwargs) -> None:
        await original(session, **kwargs)
        ready.set()
        await release.wait()

    monkeypatch.setattr(queries, "insert_document_and_request", delayed)

    async def scenario() -> None:
        task = asyncio.create_task(_scan(persistence_async_session_factory, file))
        await ready.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert _rows(migrated_engine)[0][0].storage_status == "available"
    assert len(_rows(migrated_engine)[1]) == len(_rows(migrated_engine)[2]) == 1


def test_tenant_owned_files_initiate_independently(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = _seed_file(migrated_engine), _seed_file(migrated_engine)

    async def scenario() -> None:
        await asyncio.gather(
            _scan(persistence_async_session_factory, first),
            _scan(persistence_async_session_factory, second),
        )

    asyncio.run(scenario())
    files, docs, requests = _rows(migrated_engine)
    assert len(docs) == len(requests) == 2
    for request in requests:
        file = next(file for file in files if file.id == request.source_file_id)
        doc = next(doc for doc in docs if doc.id == request.document_id)
        assert request.organization_id == file.organization_id == doc.organization_id


@pytest.mark.parametrize("mismatch", ["tenant", "source"])
def test_database_rejects_request_ownership_or_source_mismatch(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    mismatch: str,
) -> None:
    first, second = _seed_file(migrated_engine), _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, first))
    with Session(migrated_engine) as session:
        request = session.scalar(select(DocumentProcessingRequest))
        other = session.scalar(
            select(FileModel).where(FileModel.public_id == second.public_id)
        )
        assert request is not None and other is not None
        if mismatch == "tenant":
            request.organization_id = other.organization_id
        else:
            request.source_file_id = other.id
        with pytest.raises(IntegrityError):
            session.commit()


def test_delete_waits_for_initiation_and_conflicts_before_source_removal(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = _seed_file(migrated_engine)
    ready, release = asyncio.Event(), asyncio.Event()
    original = queries.insert_document_and_request

    async def delayed(session: AsyncSession, **kwargs) -> None:
        await original(session, **kwargs)
        ready.set()
        await release.wait()

    monkeypatch.setattr(queries, "insert_document_and_request", delayed)
    persistence = SqlAlchemyFilePersistence(persistence_async_session_factory)

    async def scenario() -> None:
        scan = asyncio.create_task(_scan(persistence_async_session_factory, file))
        await ready.wait()
        deletion = asyncio.create_task(
            persistence.prepare_file_deletion(
                organization_public_id=file.organization_public_id,
                file_public_id=file.public_id,
                updated_at=NOW,
            )
        )
        await asyncio.sleep(0)
        release.set()
        await scan
        with pytest.raises(FileReferencedError):
            await deletion

    asyncio.run(scenario())
    assert _rows(migrated_engine)[0][0].storage_status == "available"


def test_deletion_first_prevents_initiation_and_foreign_delete_stays_hidden(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    persistence = SqlAlchemyFilePersistence(persistence_async_session_factory)

    async def scenario() -> None:
        assert (
            await persistence.prepare_file_deletion(
                organization_public_id=uuid4(),
                file_public_id=file.public_id,
                updated_at=NOW,
            )
            is None
        )
        await persistence.prepare_file_deletion(
            organization_public_id=file.organization_public_id,
            file_public_id=file.public_id,
            updated_at=NOW,
        )
        await _scan(persistence_async_session_factory, file)

    asyncio.run(scenario())
    assert _rows(migrated_engine)[0][0].storage_status == "deleting"
    assert _rows(migrated_engine)[1:] == ([], [])


@pytest.mark.parametrize(
    "changes",
    [
        {"source_entity_tag": ""},
        {"source_entity_tag": " "},
        {"source_entity_tag": "x" * 1025},
        {"public_id": UUID(int=0)},
        {"expected_size_bytes": -1},
        {"dispatched_at": NOW - timedelta(seconds=1)},
    ],
)
def test_database_rejects_invalid_request_facts(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    changes: dict[str, object],
) -> None:
    file = _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))
    with Session(migrated_engine) as session:
        request = session.scalar(select(DocumentProcessingRequest))
        assert request is not None
        for name, value in changes.items():
            setattr(request, name, value)
        with pytest.raises(
            DataError
            if len(str(changes.get("source_entity_tag", ""))) > 1024
            else IntegrityError
        ):
            session.commit()


def test_request_lookup_hides_foreign_tenant_like_missing_file(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))

    async def scenario() -> None:
        async with persistence_async_session_factory() as session:
            assert (
                await queries.request_for_file(
                    session, replace(file, organization_public_id=uuid4())
                )
                is None
            )
            assert (
                await queries.request_for_file(
                    session, replace(file, public_id=uuid4())
                )
                is None
            )
            assert not await queries.has_document(
                session, replace(file, organization_public_id=uuid4())
            )

    asyncio.run(scenario())


def test_independent_files_can_hold_initiation_transactions_concurrently(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _seed_file(migrated_engine), _seed_file(migrated_engine)
    both_ready = asyncio.Event()
    inserts = 0
    original = queries.insert_document_and_request

    async def simultaneous_insert(session: AsyncSession, **kwargs) -> None:
        nonlocal inserts
        await original(session, **kwargs)
        inserts += 1
        if inserts == 2:
            both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=5)

    monkeypatch.setattr(queries, "insert_document_and_request", simultaneous_insert)

    async def scenario() -> None:
        await asyncio.gather(
            _scan(persistence_async_session_factory, first),
            _scan(persistence_async_session_factory, second),
        )

    asyncio.run(scenario())
    assert inserts == 2
    assert len(_rows(migrated_engine)[2]) == 2


def test_request_history_allows_generations_but_is_unique_per_document(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file = _seed_file(migrated_engine)
    asyncio.run(_scan(persistence_async_session_factory, file))
    persistence = SqlAlchemyDocumentPersistence(persistence_async_session_factory)

    async def scenario() -> Document:
        queued = await persistence.get_document(
            organization_public_id=file.organization_public_id,
            document_public_id=_rows(migrated_engine)[1][0].public_id,
        )
        assert queued is not None
        processing = queued.start_processing(at=NOW, processing_version="test-v1")
        await persistence.update_document(expected=queued, document=processing)
        await persistence.update_document(
            expected=processing,
            document=processing.fail(
                at=NOW, code="TEST_FAILURE", safe_message="Test failure"
            ),
        )
        second = (
            replace(queued, public_id=uuid4())
            .start_processing(at=NOW, processing_version="test-v2")
            .fail(at=NOW, code="TEST_FAILURE", safe_message="Test failure")
        )
        await persistence.create_document(second)
        return second

    second = asyncio.run(scenario())
    with Session(migrated_engine) as session:
        model = session.scalar(
            select(DocumentModel).where(DocumentModel.public_id == second.public_id)
        )
        assert model is not None
        session.add(
            DocumentProcessingRequest(
                public_id=uuid4(),
                document_id=model.id,
                organization_id=model.organization_id,
                source_file_id=model.source_file_id,
                source_entity_tag="verified-v1",
                expected_size_bytes=42,
                created_at=NOW,
            )
        )
        session.commit()
        session.add(
            DocumentProcessingRequest(
                public_id=uuid4(),
                document_id=model.id,
                organization_id=model.organization_id,
                source_file_id=model.source_file_id,
                source_entity_tag="verified-v1",
                expected_size_bytes=42,
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError) as captured:
            session.commit()
        assert (
            captured.value.orig.diag.constraint_name == "uq_document_requests_document"
        )


def test_clean_malware_application_uses_atomic_initiation_handoff(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from unittest.mock import AsyncMock, Mock

    from nexus.files.application import ApplyMalwareScanResult
    from nexus.files.ports import (
        MalwareScanResultEvent,
        MalwareScanVerdict,
        ObjectStorage,
        StoredObjectProperties,
    )

    file = _seed_file(migrated_engine)
    storage = Mock(spec=ObjectStorage)
    storage.get_object_properties = AsyncMock(
        return_value=StoredObjectProperties(
            entity_tag="verified-v1",
            size_bytes=42,
            metadata={},
        )
    )
    handler = ApplyMalwareScanResult(
        object_storage=storage,
        persistence=SqlAlchemyFilePersistence(persistence_async_session_factory),
        initiation=SqlAlchemyDocumentInitiationPersistence(
            persistence_async_session_factory
        ),
        clock=lambda: NOW,
    )
    event = MalwareScanResultEvent(
        event_id="scan-1",
        source="trusted-scanner",
        storage_key=file.storage_key,
        occurred_at=NOW,
        entity_tag="verified-v1",
        verdict=MalwareScanVerdict.CLEAN,
    )
    asyncio.run(handler.handle(event))
    asyncio.run(handler.handle(event))
    assert _rows(migrated_engine)[0][0].storage_status == "available"
    assert len(_rows(migrated_engine)[1]) == len(_rows(migrated_engine)[2]) == 1
