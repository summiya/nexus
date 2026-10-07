import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.persistence.test_document_persistence import (
    STARTED_AT,
    _document,
    _seed_file,
)

from nexus.documents.application.normalize_document import NormalizeDocument
from nexus.documents.application.segment_document import SegmentDocument
from nexus.documents.domain import DocumentStatus
from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedDocument,
    ExtractedListItem,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind as Kind,
)
from nexus.documents.domain.segmented_document import DocumentChunkKind
from nexus.documents.ports.chunk_persistence import (
    ChunkConflictError,
    ChunkPersistenceError,
)
from nexus.infrastructure.persistence import _document_chunk_queries as queries
from nexus.infrastructure.persistence import _document_queries
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_chunk import (
    SqlAlchemyDocumentChunkPersistence,
)
from nexus.infrastructure.persistence.models.document import Document as DocumentModel
from nexus.infrastructure.persistence.models.document_chunk import (
    DocumentChunk,
    DocumentChunkSet,
)
from nexus.infrastructure.persistence.models.organization import Organization


@pytest.fixture
def context(migrated_database, persistence_async_session_factory):
    config, engine = migrated_database
    command.upgrade(config, "head")
    org, file = _seed_file(engine)
    document = (
        _document(org, file)
        .start_processing(at=STARTED_AT, processing_version="pipeline-v1")
        .record_extractor_version("1")
    )
    asyncio.run(
        SqlAlchemyDocumentPersistence(
            persistence_async_session_factory
        ).create_document(document)
    )
    result = segmented(document)
    return engine, persistence_async_session_factory, document, result


def segmented(document, *, pages=False):
    if pages:
        blocks = (
            ExtractedBlock(0, Kind.PARAGRAPH, "page two", page_number=2),
            ExtractedBlock(1, Kind.PARAGRAPH, "page four", page_number=4),
        )
    else:
        blocks = (
            ExtractedBlock(0, Kind.HEADING, "Title", 1, 2, heading_level=1),
            ExtractedBlock(1, Kind.PARAGRAPH, "é first", 2, 3),
            ExtractedBlock(2, Kind.PARAGRAPH, "second", 3, 4),
            ExtractedBlock(3, Kind.TEXT, "quoted", 4, 5, quote_depth=1),
            ExtractedBlock(
                4,
                Kind.PARAGRAPH,
                "item",
                5,
                6,
                list_item=ExtractedListItem(5, 5, 2, True, 0),
            ),
            ExtractedBlock(5, Kind.CODE, "a" * 25, 6, 7),
        )
    return SegmentDocument(preferred_chunk_bytes=10, max_chunk_bytes=20).execute(
        NormalizeDocument().execute(
            ExtractedDocument(
                document.source_file_public_id,
                "verified-etag",
                "nexus.test",
                "1",
                blocks,
                5 if pages else None,
            )
        )
    )


def write(persistence, document, result):
    return persistence.persist_chunk_set(expected=document, segmented_document=result)


def read(persistence, document):
    return persistence.get_chunk_set(
        organization_public_id=document.organization_public_id,
        document_public_id=document.public_id,
    )


def row_counts(engine):
    with Session(engine) as session:
        return session.scalar(
            select(func.count()).select_from(DocumentChunkSet)
        ), session.scalar(select(func.count()).select_from(DocumentChunk))


@pytest.mark.parametrize("pages", [False, True])
def test_round_trip_duplicate_and_terminal_history(context, pages):
    engine, sessions, document, _ = context
    result = segmented(document, pages=pages)
    persistence = SqlAlchemyDocumentChunkPersistence(sessions, batch_size=2)
    asyncio.run(write(persistence, document, result))
    assert asyncio.run(read(persistence, document)) == result
    asyncio.run(write(persistence, document, result))
    assert row_counts(engine) == (1, len(result.chunks))
    if pages:
        assert asyncio.run(read(persistence, document)).chunks[0].page_numbers == (2, 4)
    else:
        assert any(c.kind is DocumentChunkKind.LIST for c in result.chunks)
        assert any(c.contributions[0].text_start is not None for c in result.chunks)
        assert result.chunks[0].section_path == (0,)
        assert len(result.chunks[0].contributions) == 2
    current = asyncio.run(
        SqlAlchemyDocumentPersistence(sessions).get_document(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )
    )
    assert current == document  # Chunk persistence never advances the lifecycle.
    terminal = document.complete(at=STARTED_AT + timedelta(minutes=1))
    asyncio.run(
        SqlAlchemyDocumentPersistence(sessions).update_document(
            expected=document, document=terminal
        )
    )
    assert asyncio.run(read(persistence, terminal)) == result
    with pytest.raises(ChunkConflictError):
        asyncio.run(write(persistence, terminal, result))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_entity_tag", "different"),
        ("extractor_id", "different"),
        ("normalizer_id", "different"),
        ("normalizer_version", "2"),
        ("segmenter_id", "different"),
        ("segmenter_version", "2"),
        ("preferred_chunk_bytes", 11),
        ("max_chunk_bytes", 21),
        ("max_source_contributions", 129),
    ],
)
def test_changed_set_metadata_conflicts(context, field, value):
    engine, sessions, document, result = context
    persistence = SqlAlchemyDocumentChunkPersistence(sessions)
    asyncio.run(write(persistence, document, result))
    with pytest.raises(
        ChunkConflictError, match="^Document chunk persistence conflict$"
    ):
        asyncio.run(write(persistence, document, replace(result, **{field: value})))
    assert asyncio.run(read(persistence, document)) == result
    assert row_counts(engine) == (1, len(result.chunks))


@pytest.mark.parametrize(
    "change", ["text", "kind", "contribution", "order", "count", "section"]
)
def test_changed_chunk_semantics_conflict(context, change):
    _, sessions, document, result = context
    persistence = SqlAlchemyDocumentChunkPersistence(sessions)
    asyncio.run(write(persistence, document, result))
    chunks = list(result.chunks)
    if change == "text":
        chunks[0] = replace(chunks[0], text="changed")
    elif change == "kind":
        chunks[0] = replace(
            chunks[0],
            kind=DocumentChunkKind.TEXT,
            contributions=tuple(
                replace(c, kind=Kind.TEXT) for c in chunks[0].contributions
            ),
        )
    elif change == "contribution":
        chunks[0] = replace(
            chunks[0],
            contributions=(
                replace(chunks[0].contributions[0], end_line=4),
                chunks[0].contributions[1],
            ),
        )
    elif change == "order":
        chunks[0] = replace(chunks[0], text="second then first")
    elif change == "section":
        chunks[0] = replace(chunks[0], section_path=())
    else:
        chunks.pop()
    with pytest.raises(ChunkConflictError):
        asyncio.run(write(persistence, document, replace(result, chunks=tuple(chunks))))


@pytest.mark.parametrize(
    "status", [DocumentStatus.QUEUED, DocumentStatus.COMPLETED, DocumentStatus.FAILED]
)
def test_inactive_lifecycle_rejected(context, status):
    engine, sessions, processing, result = context
    if status is DocumentStatus.QUEUED:
        expected = _document(
            processing.organization_public_id, processing.source_file_public_id
        )
    elif status is DocumentStatus.COMPLETED:
        expected = processing.complete(at=STARTED_AT)
    else:
        expected = processing.fail(at=STARTED_AT, code="FAILED", safe_message="Failed")
    with pytest.raises(ChunkConflictError):
        asyncio.run(
            write(SqlAlchemyDocumentChunkPersistence(sessions), expected, result)
        )
    assert row_counts(engine) == (0, 0)


@pytest.mark.parametrize(
    "change",
    ["no_extractor", "extractor", "source", "processing_version", "started_at"],
)
def test_incompatible_or_stale_context_rejected(context, change):
    engine, sessions, document, result = context
    kwargs = {
        "no_extractor": {"extractor_version": None},
        "extractor": {"extractor_version": "2"},
        "source": {"source_file_public_id": uuid4()},
        "processing_version": {"processing_version": "other"},
        "started_at": {"processing_started_at": STARTED_AT + timedelta(seconds=1)},
    }[change]
    with pytest.raises(ChunkConflictError):
        asyncio.run(
            write(
                SqlAlchemyDocumentChunkPersistence(sessions),
                replace(document, **kwargs),
                result,
            )
        )
    assert row_counts(engine) == (0, 0)


def test_tenant_isolation_missing_and_foreign_are_indistinguishable(context):
    engine, sessions, document, result = context
    persistence = SqlAlchemyDocumentChunkPersistence(sessions)
    asyncio.run(write(persistence, document, result))
    foreign_org, _ = _seed_file(engine)
    for disguised in (
        replace(document, organization_public_id=foreign_org),
        replace(document, public_id=uuid4()),
    ):
        with pytest.raises(
            ChunkConflictError, match="^Document chunk persistence conflict$"
        ):
            asyncio.run(write(persistence, disguised, result))
        assert asyncio.run(read(persistence, disguised)) is None
    assert asyncio.run(read(persistence, document)) == result
    assert row_counts(engine) == (1, len(result.chunks))


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_writers_converge_or_conflict(context, monkeypatch, different):
    engine, sessions, document, result = context
    entered, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_insert = queries.insert_chunks
    calls = 0

    async def delayed(session, rows):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        await original_insert(session, rows)

    monkeypatch.setattr(queries, "insert_chunks", delayed)
    changed = replace(result, segmenter_version="2") if different else result

    async def scenario():
        persistence = SqlAlchemyDocumentChunkPersistence(sessions)
        first = asyncio.create_task(write(persistence, document, result))
        await entered.wait()

        async def second_write():
            second_started.set()
            await write(persistence, document, changed)

        second = asyncio.create_task(second_write())
        await second_started.wait()
        await asyncio.sleep(0)
        assert not second.done()
        # No partial state is visible while the first writer owns the lock.
        assert await read(persistence, document) is None
        release.set()
        outcomes = await asyncio.gather(first, second, return_exceptions=True)
        assert outcomes[0] is None
        assert (
            isinstance(outcomes[1], ChunkConflictError)
            if different
            else outcomes[1] is None
        )

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert row_counts(engine) == (1, len(result.chunks))
    assert (
        asyncio.run(read(SqlAlchemyDocumentChunkPersistence(sessions), document))
        == result
    )


def test_independent_documents_are_not_serialized(context, monkeypatch):
    engine, sessions, first_document, first_result = context
    org, file = _seed_file(engine)
    second_document = (
        _document(org, file)
        .start_processing(at=STARTED_AT, processing_version="pipeline-v1")
        .record_extractor_version("1")
    )
    asyncio.run(
        SqlAlchemyDocumentPersistence(sessions).create_document(second_document)
    )
    second_result = segmented(second_document)
    original = queries.insert_chunks
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(session, rows):
        if rows[0]["document_id"] == first_id:
            entered.set()
            await release.wait()
        await original(session, rows)

    with Session(engine) as session:
        first_id = session.scalar(
            select(DocumentModel.id).where(
                DocumentModel.public_id == first_document.public_id
            )
        )
    monkeypatch.setattr(queries, "insert_chunks", delayed)

    async def scenario():
        persistence = SqlAlchemyDocumentChunkPersistence(sessions)
        first = asyncio.create_task(write(persistence, first_document, first_result))
        await entered.wait()
        try:
            await asyncio.wait_for(
                write(persistence, second_document, second_result), 3
            )
            assert not first.done()
        finally:
            release.set()
            await first

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_batch_rolls_back_complete_set_and_retry_succeeds(
    context, monkeypatch, cancel
):
    engine, sessions, document, result = context
    original = queries.insert_chunks
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def failed(session, rows):
        nonlocal calls
        await original(session, rows)
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()
            raise ValueError("private payload must not escape")

    monkeypatch.setattr(queries, "insert_chunks", failed)

    async def scenario():
        task = asyncio.create_task(
            write(
                SqlAlchemyDocumentChunkPersistence(sessions, batch_size=1),
                document,
                result,
            )
        )
        await entered.wait()
        if cancel:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            task.cancel()  # Repeated cancellation must still settle resources.
        release.set()
        with pytest.raises(asyncio.CancelledError if cancel else ChunkPersistenceError):
            await task

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert row_counts(engine) == (0, 0)
    monkeypatch.setattr(queries, "insert_chunks", original)
    asyncio.run(write(SqlAlchemyDocumentChunkPersistence(sessions), document, result))
    assert row_counts(engine) == (1, len(result.chunks))


def test_cancellation_settles_committed_set_and_retry_verifies(context, monkeypatch):
    engine, sessions, document, result = context
    original = queries.insert_chunks
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(session, rows):
        await original(session, rows)
        entered.set()
        await release.wait()

    monkeypatch.setattr(queries, "insert_chunks", delayed)

    async def scenario():
        persistence = SqlAlchemyDocumentChunkPersistence(sessions)
        task = asyncio.create_task(write(persistence, document, result))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await read(persistence, document) == result
        await write(persistence, document, result)

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert row_counts(engine) == (1, len(result.chunks))


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_row",
        "count",
        "slice_bool",
        "extra_field",
        "settings",
        "page_count",
        "index",
        "contribution_order",
    ],
)
def test_corrupt_stored_set_fails_safely_for_read_and_duplicate(context, corruption):
    engine, sessions, document, result = context
    persistence = SqlAlchemyDocumentChunkPersistence(sessions)
    asyncio.run(write(persistence, document, result))
    with Session(engine) as session:
        if corruption == "missing_row":
            session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.chunk_index == len(result.chunks) - 1
                )
            )
        elif corruption == "index":
            session.execute(
                update(DocumentChunk)
                .where(DocumentChunk.chunk_index == len(result.chunks) - 1)
                .values(chunk_index=99)
            )
        elif corruption == "count":
            session.execute(
                update(DocumentChunkSet).values(chunk_count=len(result.chunks) + 1)
            )
        elif corruption == "settings":
            session.execute(update(DocumentChunkSet).values(max_chunk_bytes=10))
        elif corruption == "page_count":
            session.execute(update(DocumentChunkSet).values(page_count=1))
        else:
            row = session.scalar(
                select(DocumentChunk).order_by(DocumentChunk.chunk_index)
            )
            payload = [dict(c) for c in row.contributions]
            if corruption == "contribution_order":
                payload.reverse()
            else:
                payload[0][
                    "source_block_index" if corruption == "slice_bool" else "unknown"
                ] = True
            session.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == row.id)
                .values(contributions=payload)
            )
        session.commit()
    for operation in (
        lambda: read(persistence, document),
        lambda: write(persistence, document, result),
    ):
        with pytest.raises(
            ChunkPersistenceError, match="^Document chunk persistence failed$"
        ):
            asyncio.run(operation())


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", " "),
        ("kind", "invalid"),
        ("chunk_index", -1),
        ("contributions", []),
        ("contributions", {}),
        ("organization_id", 999999),
    ],
)
def test_database_rejects_invalid_chunk_rows(context, field, value):
    engine, sessions, document, result = context
    asyncio.run(write(SqlAlchemyDocumentChunkPersistence(sessions), document, result))
    with Session(engine) as session:
        row = session.scalar(select(DocumentChunk).order_by(DocumentChunk.chunk_index))
        with pytest.raises(IntegrityError):
            session.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == row.id)
                .values(**{field: value})
            )
            session.commit()
        session.rollback()
    assert row_counts(engine) == (1, len(result.chunks))


def test_database_rejects_duplicate_index_and_foreign_header(context):
    engine, sessions, document, result = context
    asyncio.run(write(SqlAlchemyDocumentChunkPersistence(sessions), document, result))
    foreign_org, _ = _seed_file(engine)
    with Session(engine) as session:
        foreign_id = session.scalar(
            select(Organization.id).where(Organization.public_id == foreign_org)
        )
        row = session.scalar(select(DocumentChunk).order_by(DocumentChunk.chunk_index))
        with pytest.raises(IntegrityError):
            session.execute(update(DocumentChunk).values(organization_id=foreign_id))
            session.commit()
        session.rollback()
        values = queries.chunk_values(result.chunks[0])
        with pytest.raises(IntegrityError):
            session.add(
                DocumentChunk(
                    document_id=row.document_id,
                    organization_id=row.organization_id,
                    **values,
                )
            )
            session.commit()
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(update(DocumentChunkSet).values(organization_id=foreign_id))
            session.commit()
        session.rollback()


@pytest.mark.parametrize(
    "limits",
    [
        {"max_chunks": 1},
        {"max_text_bytes": 1},
        {"max_contributions_per_chunk": 1},
        {"max_total_contributions": 1},
        {"max_provenance_bytes": 1},
    ],
)
def test_bounds_reject_before_lock(context, monkeypatch, limits):
    engine, sessions, document, result = context

    async def unexpected(*args, **kwargs):
        pytest.fail("Resource rejection must occur before locking")

    monkeypatch.setattr(_document_queries, "document_for_update", unexpected)
    with pytest.raises(ChunkPersistenceError):
        asyncio.run(
            write(
                SqlAlchemyDocumentChunkPersistence(sessions, **limits), document, result
            )
        )
    assert row_counts(engine) == (0, 0)


def test_exact_resource_bounds_round_trip(context):
    _, sessions, document, result = context
    contributions = [queries.chunk_values(c)["contributions"] for c in result.chunks]
    persistence = SqlAlchemyDocumentChunkPersistence(
        sessions,
        max_chunks=len(result.chunks),
        max_text_bytes=sum(len(c.text.encode("utf-8")) for c in result.chunks),
        max_contributions_per_chunk=max(len(c) for c in contributions),
        max_total_contributions=sum(len(c) for c in contributions),
        max_provenance_bytes=sum(
            len(json.dumps(c, ensure_ascii=False).encode("utf-8"))
            for c in contributions
        ),
    )
    asyncio.run(write(persistence, document, result))
    assert asyncio.run(read(persistence, document)) == result
    asyncio.run(write(persistence, document, result))


@pytest.mark.parametrize(
    "limits",
    [
        {"max_chunks": 1},
        {"max_text_bytes": 1},
        {"max_contributions_per_chunk": 1},
        {"max_total_contributions": 1},
        {"max_provenance_bytes": 1},
    ],
)
def test_stored_resource_bounds_checked_before_loading_rows(
    context, monkeypatch, limits
):
    _, sessions, document, result = context
    asyncio.run(write(SqlAlchemyDocumentChunkPersistence(sessions), document, result))

    async def unexpected(*args, **kwargs):
        pytest.fail("Oversized stored data must not be loaded")

    monkeypatch.setattr(queries, "get_chunks", unexpected)
    with pytest.raises(ChunkPersistenceError):
        asyncio.run(
            read(SqlAlchemyDocumentChunkPersistence(sessions, **limits), document)
        )


def test_changed_page_count_conflicts(context):
    _, sessions, document, _ = context
    result = segmented(document, pages=True)
    persistence = SqlAlchemyDocumentChunkPersistence(sessions)
    asyncio.run(write(persistence, document, result))
    with pytest.raises(ChunkConflictError):
        asyncio.run(write(persistence, document, replace(result, page_count=6)))
    assert asyncio.run(read(persistence, document)) == result


def test_cancellation_after_commit_retries_existing_set(context, monkeypatch):
    engine, sessions, document, result = context
    persistence = SqlAlchemyDocumentChunkPersistence(sessions)
    original = persistence._persist
    committed, release = asyncio.Event(), asyncio.Event()

    async def delayed_return(*args):
        await original(*args)
        committed.set()
        await release.wait()

    monkeypatch.setattr(persistence, "_persist", delayed_return)

    async def scenario():
        task = asyncio.create_task(write(persistence, document, result))
        await committed.wait()
        assert await read(persistence, document) == result
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        monkeypatch.setattr(persistence, "_persist", original)
        await write(persistence, document, result)

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert row_counts(engine) == (1, len(result.chunks))
