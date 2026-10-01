from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from nexus.documents.domain import Document
from nexus.documents.ports import (
    DocumentConflictError,
    DocumentReferenceError,
)
from nexus.infrastructure.persistence import _document_queries as queries
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.file import File as FileModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User

CREATED_AT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
STARTED_AT = CREATED_AT + timedelta(minutes=1)
FINISHED_AT = STARTED_AT + timedelta(minutes=2)


@pytest.fixture
def migrated_engine(migrated_database: tuple[Config, Engine]) -> Engine:
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


def _seed_file(engine: Engine) -> tuple[UUID, UUID]:
    organization_public_id = uuid4()
    file_public_id = uuid4()
    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Document Organization",
            slug=f"documents-{uuid4().hex[:12]}",
            status="active",
        )
        user = User(
            public_id=uuid4(),
            organization=organization,
            email=f"{uuid4().hex}@example.com",
            status="active",
        )
        session.add(user)
        session.flush()
        session.add(
            FileModel(
                public_id=file_public_id,
                organization_id=organization.id,
                created_by_user_id=user.id,
                original_name="document.pdf",
                mime_type="application/pdf",
                size_bytes=42,
                storage_key=f"files/{uuid4().hex}",
                storage_status="available",
                checksum_sha256=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        session.commit()
    return organization_public_id, file_public_id


def _document(organization_public_id: UUID, file_public_id: UUID) -> Document:
    return Document(
        public_id=uuid4(),
        organization_public_id=organization_public_id,
        source_file_public_id=file_public_id,
        created_at=CREATED_AT,
    )


def _processing(document: Document, *, extractor: bool = False) -> Document:
    processing = document.start_processing(
        at=STARTED_AT,
        processing_version="pipeline-v1",
    )
    if extractor:
        return processing.record_extractor_version("pdf-v1")
    return processing


def _persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyDocumentPersistence:
    return SqlAlchemyDocumentPersistence(session_factory)


@pytest.mark.parametrize(
    "snapshot_factory",
    [
        pytest.param(lambda document: document, id="queued"),
        pytest.param(lambda document: _processing(document), id="processing"),
        pytest.param(
            lambda document: _processing(document, extractor=True),
            id="processing-with-extractor",
        ),
        pytest.param(
            lambda document: _processing(document, extractor=True).complete(
                at=FINISHED_AT
            ),
            id="completed",
        ),
        pytest.param(
            lambda document: _processing(document).fail(
                at=FINISHED_AT,
                code="EXTRACTION_FAILED",
                safe_message="Document extraction failed.",
            ),
            id="failed",
        ),
    ],
)
def test_document_snapshots_round_trip(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    snapshot_factory: Callable[[Document], Document],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    document = snapshot_factory(_document(organization_public_id, file_public_id))
    persistence = _persistence(persistence_async_session_factory)

    asyncio.run(persistence.create_document(document))
    stored = asyncio.run(
        persistence.get_document(
            organization_public_id=organization_public_id,
            document_public_id=document.public_id,
        )
    )

    assert stored == document
    assert isinstance(stored, Document)
    assert not hasattr(stored, "id")


def test_document_lookup_is_organization_scoped(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    other_organization_public_id, _ = _seed_file(migrated_engine)
    document = _document(organization_public_id, file_public_id)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_document(document))

    hidden = asyncio.run(
        persistence.get_document(
            organization_public_id=other_organization_public_id,
            document_public_id=document.public_id,
        )
    )
    missing = asyncio.run(
        persistence.get_document(
            organization_public_id=organization_public_id,
            document_public_id=uuid4(),
        )
    )

    assert hidden is None
    assert missing is None


def test_create_rejects_cross_tenant_source_file(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, _ = _seed_file(migrated_engine)
    _, other_file_public_id = _seed_file(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)

    with pytest.raises(DocumentReferenceError):
        asyncio.run(
            persistence.create_document(
                _document(organization_public_id, other_file_public_id)
            )
        )


def test_database_rejects_cross_tenant_source_file_relationship(
    migrated_engine: Engine,
) -> None:
    organization_public_id, _ = _seed_file(migrated_engine)
    _, other_file_public_id = _seed_file(migrated_engine)
    with Session(migrated_engine) as session:
        organization_id = session.scalar(
            select(Organization.id).where(
                Organization.public_id == organization_public_id
            )
        )
        other_file_id = session.scalar(
            select(FileModel.id).where(FileModel.public_id == other_file_public_id)
        )
        session.add(
            DocumentModel(
                public_id=uuid4(),
                organization_id=organization_id,
                source_file_id=other_file_id,
                status="queued",
                created_at=CREATED_AT,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    "values",
    [
        {"status": "unknown"},
        {"status": "processing"},
        {"status": "queued", "extractor_version": "pdf-v1"},
        {
            "status": "processing",
            "processing_version": " pipeline-v1",
            "processing_started_at": STARTED_AT,
        },
        {
            "status": "failed",
            "processing_version": "pipeline-v1",
            "processing_started_at": STARTED_AT,
            "failed_at": FINISHED_AT,
            "failure_code": "invalid",
            "failure_safe_message": "Failed safely.",
        },
        {
            "status": "completed",
            "processing_version": "pipeline-v1",
            "processing_started_at": STARTED_AT,
            "processing_completed_at": CREATED_AT,
        },
    ],
)
def test_database_rejects_invalid_document_snapshots(
    migrated_engine: Engine,
    values: dict[str, object],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    with Session(migrated_engine) as session:
        organization_id = session.scalar(
            select(Organization.id).where(
                Organization.public_id == organization_public_id
            )
        )
        file_id = session.scalar(
            select(FileModel.id).where(FileModel.public_id == file_public_id)
        )
        model_values: dict[str, object] = {
            "public_id": uuid4(),
            "organization_id": organization_id,
            "source_file_id": file_id,
            "status": "queued",
            "created_at": CREATED_AT,
        }
        model_values.update(values)
        session.add(DocumentModel(**model_values))
        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_public_identity_maps_to_conflict(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    other_organization_public_id, other_file_public_id = _seed_file(migrated_engine)
    document = _document(organization_public_id, file_public_id)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_document(document))

    duplicate = replace(
        _document(other_organization_public_id, other_file_public_id),
        public_id=document.public_id,
    )
    with pytest.raises(DocumentConflictError):
        asyncio.run(persistence.create_document(duplicate))


def test_active_document_uniqueness_and_terminal_history(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    active = _document(organization_public_id, file_public_id)
    asyncio.run(persistence.create_document(active))

    with pytest.raises(DocumentConflictError):
        asyncio.run(
            persistence.create_document(
                _document(organization_public_id, file_public_id)
            )
        )

    processing = _processing(active)
    completed = processing.complete(at=FINISHED_AT)
    asyncio.run(persistence.update_document(expected=active, document=processing))
    with pytest.raises(DocumentConflictError):
        asyncio.run(
            persistence.create_document(
                _document(organization_public_id, file_public_id)
            )
        )
    asyncio.run(persistence.update_document(expected=processing, document=completed))

    failed_history = _processing(
        _document(organization_public_id, file_public_id)
    ).fail(
        at=FINISHED_AT,
        code="PROCESSING_FAILED",
        safe_message="Processing failed.",
    )
    next_active = _document(organization_public_id, file_public_id)
    asyncio.run(persistence.create_document(failed_history))
    asyncio.run(persistence.create_document(next_active))

    with Session(migrated_engine) as session:
        rows = session.scalars(
            select(DocumentModel).where(
                DocumentModel.source_file_id
                == select(FileModel.id)
                .where(FileModel.public_id == file_public_id)
                .scalar_subquery()
            )
        ).all()
    assert {row.status for row in rows} == {"completed", "failed", "queued"}


@pytest.mark.parametrize(
    ("expected_factory", "successor_factory"),
    [
        pytest.param(
            lambda document: document,
            lambda document: _processing(document),
            id="queued-to-processing",
        ),
        pytest.param(
            lambda document: _processing(document),
            lambda document: _processing(document).record_extractor_version("pdf-v1"),
            id="processing-records-first-extractor",
        ),
        pytest.param(
            lambda document: _processing(document),
            lambda document: _processing(document).complete(at=FINISHED_AT),
            id="processing-to-completed",
        ),
        pytest.param(
            lambda document: _processing(document),
            lambda document: _processing(document).fail(
                at=FINISHED_AT,
                code="PROCESSING_FAILED",
                safe_message="Processing failed.",
            ),
            id="processing-to-failed",
        ),
    ],
)
def test_update_accepts_only_dp01_lifecycle_successors(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    expected_factory: Callable[[Document], Document],
    successor_factory: Callable[[Document], Document],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    initial = _document(organization_public_id, file_public_id)
    expected = expected_factory(initial)
    successor = successor_factory(initial)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_document(expected))

    asyncio.run(persistence.update_document(expected=expected, document=successor))

    stored = asyncio.run(
        persistence.get_document(
            organization_public_id=organization_public_id,
            document_public_id=initial.public_id,
        )
    )
    assert stored == successor


@pytest.mark.parametrize(
    ("expected_factory", "illegal_successor_factory"),
    [
        pytest.param(
            lambda document: document,
            lambda document: _processing(document).complete(at=FINISHED_AT),
            id="queued-to-completed",
        ),
        pytest.param(
            lambda document: document,
            lambda document: _processing(document).fail(
                at=FINISHED_AT,
                code="PROCESSING_FAILED",
                safe_message="Processing failed.",
            ),
            id="queued-to-failed",
        ),
        pytest.param(
            lambda document: _processing(document, extractor=True),
            lambda document: replace(
                _processing(document, extractor=True),
                extractor_version="pdf-v2",
            ),
            id="processing-replaces-recorded-extractor",
        ),
        pytest.param(
            lambda document: _processing(document).complete(at=FINISHED_AT),
            lambda document: _processing(document).fail(
                at=FINISHED_AT,
                code="PROCESSING_FAILED",
                safe_message="Processing failed.",
            ),
            id="completed-to-failed",
        ),
        pytest.param(
            lambda document: _processing(document).fail(
                at=FINISHED_AT,
                code="PROCESSING_FAILED",
                safe_message="Processing failed.",
            ),
            lambda document: _processing(document).complete(at=FINISHED_AT),
            id="failed-to-completed",
        ),
    ],
)
def test_update_rejects_illegal_or_terminal_lifecycle_successors(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    expected_factory: Callable[[Document], Document],
    illegal_successor_factory: Callable[[Document], Document],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    initial = _document(organization_public_id, file_public_id)
    expected = expected_factory(initial)
    illegal_successor = illegal_successor_factory(initial)
    persistence = _persistence(persistence_async_session_factory)
    asyncio.run(persistence.create_document(expected))

    with pytest.raises(DocumentConflictError, match="Document persistence conflict"):
        asyncio.run(
            persistence.update_document(
                expected=expected,
                document=illegal_successor,
            )
        )

    stored = asyncio.run(
        persistence.get_document(
            organization_public_id=organization_public_id,
            document_public_id=initial.public_id,
        )
    )
    assert stored == expected


def test_update_rejects_stale_snapshot_and_immutable_identity_change(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    _, other_file_public_id = _seed_file(migrated_engine)
    persistence = _persistence(persistence_async_session_factory)
    queued = _document(organization_public_id, file_public_id)
    asyncio.run(persistence.create_document(queued))
    processing = _processing(queued)
    asyncio.run(persistence.update_document(expected=queued, document=processing))

    with pytest.raises(DocumentConflictError):
        asyncio.run(persistence.update_document(expected=queued, document=processing))
    with pytest.raises(DocumentConflictError):
        asyncio.run(
            persistence.update_document(
                expected=processing,
                document=replace(
                    processing,
                    source_file_public_id=other_file_public_id,
                ),
            )
        )


def test_create_transaction_settles_before_cancellation_propagates(
    migrated_engine: Engine,
    persistence_async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_public_id, file_public_id = _seed_file(migrated_engine)
    document = _document(organization_public_id, file_public_id)
    transaction_started = asyncio.Event()
    allow_transaction_to_finish = asyncio.Event()
    original_insert = queries.insert_document

    async def delayed_insert(session: AsyncSession, document: Document) -> None:
        await original_insert(session, document)
        transaction_started.set()
        await allow_transaction_to_finish.wait()

    monkeypatch.setattr(queries, "insert_document", delayed_insert)

    async def scenario() -> None:
        operation = asyncio.create_task(
            _persistence(persistence_async_session_factory).create_document(document)
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
        assert (
            session.scalar(
                select(DocumentModel).where(
                    DocumentModel.public_id == document.public_id
                )
            )
            is not None
        )
