import asyncio
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import update
from sqlalchemy.orm import Session
from tests.integration.persistence.test_document_chunk_persistence import (
    segmented,
    write,
)
from tests.integration.persistence.test_document_persistence import (
    STARTED_AT,
    _document,
    _seed_file,
)

from nexus.documents.domain import DocumentFailure, DocumentStatus
from nexus.documents.ports.chunk_persistence import (
    ChunkConflictError,
    ChunkPersistenceError,
)
from nexus.documents.ports.persistence import DocumentConflictError
from nexus.documents.ports.processing import ProcessingOutcome
from nexus.infrastructure.persistence import _document_queries
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_chunk import (
    SqlAlchemyDocumentChunkPersistence,
)
from nexus.infrastructure.persistence.document_finalization import (
    SqlAlchemyDocumentFinalization,
)
from nexus.infrastructure.persistence.models.document_chunk import DocumentChunkSet


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
    return engine, persistence_async_session_factory, document, segmented(document)


FAILURE = DocumentFailure("MALFORMED_DOCUMENT", "Document content is malformed.")


async def finish(finalizer, document, failure=None):
    return await finalizer.finalize(
        organization_public_id=document.organization_public_id,
        document_public_id=document.public_id,
        failure=failure,
    )


async def current(sessions, document):
    return await SqlAlchemyDocumentPersistence(sessions).get_document(
        organization_public_id=document.organization_public_id,
        document_public_id=document.public_id,
    )


@pytest.mark.parametrize("failure", [None, FAILURE])
def test_committed_chunks_win_both_completion_and_failure(context, failure):
    _, sessions, document, result = context

    async def run():
        await write(SqlAlchemyDocumentChunkPersistence(sessions), document, result)
        finalizer = SqlAlchemyDocumentFinalization(sessions)
        assert (
            await finish(finalizer, document, failure)
        ).outcome is ProcessingOutcome.SUCCESS
        assert (await current(sessions, document)).status is DocumentStatus.COMPLETED
        assert (
            await finish(finalizer, document, FAILURE)
        ).outcome is ProcessingOutcome.SUCCESS

    asyncio.run(run())


def test_failure_committed_first_prevents_later_chunk_write(context):
    _, sessions, document, result = context

    async def run():
        finalizer = SqlAlchemyDocumentFinalization(sessions)
        assert (
            await finish(finalizer, document, FAILURE)
        ).outcome is ProcessingOutcome.TERMINAL_FINALIZED
        with pytest.raises(ChunkConflictError):
            await write(SqlAlchemyDocumentChunkPersistence(sessions), document, result)
        stored = await current(sessions, document)
        assert stored.status is DocumentStatus.FAILED and stored.failure == FAILURE

    asyncio.run(run())


def test_failure_and_chunk_transactions_race_on_same_document_lock(context):
    _, sessions, document, result = context

    async def run():
        outcomes = await asyncio.gather(
            write(SqlAlchemyDocumentChunkPersistence(sessions), document, result),
            finish(SqlAlchemyDocumentFinalization(sessions), document, FAILURE),
            return_exceptions=True,
        )
        stored = await current(sessions, document)
        chunks = await SqlAlchemyDocumentChunkPersistence(sessions).get_chunk_set(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )
        if stored.status is DocumentStatus.FAILED:
            assert chunks is None and isinstance(outcomes[0], ChunkConflictError)
        else:
            assert stored.status is DocumentStatus.COMPLETED and chunks == result
        assert not isinstance(outcomes[1], Exception)

    asyncio.run(run())


def test_no_chunks_cannot_complete_and_foreign_or_missing_ids_do_not_mutate(context):
    _, sessions, document, _ = context

    async def run():
        finalizer = SqlAlchemyDocumentFinalization(sessions)
        with pytest.raises(DocumentConflictError):
            await finish(finalizer, document)
        for org, doc in [
            (uuid4(), document.public_id),
            (document.organization_public_id, uuid4()),
        ]:
            with pytest.raises(DocumentConflictError):
                await finalizer.finalize(
                    organization_public_id=org, document_public_id=doc, failure=FAILURE
                )
        assert await current(sessions, document) == document

    asyncio.run(run())


def test_corrupt_chunk_set_cannot_be_claimed_as_success(context):
    engine, sessions, document, result = context
    asyncio.run(write(SqlAlchemyDocumentChunkPersistence(sessions), document, result))
    with Session(engine) as session:
        session.execute(update(DocumentChunkSet).values(chunk_count=999))
        session.commit()
    with pytest.raises(ChunkPersistenceError):
        asyncio.run(finish(SqlAlchemyDocumentFinalization(sessions), document, FAILURE))
    assert asyncio.run(current(sessions, document)) == document


def test_finalization_cancellation_settles_transaction_before_return(
    context, monkeypatch
):
    _, sessions, document, _ = context

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        original = _document_queries.replace_document_snapshot

        async def gated(*args, **kwargs):
            await original(*args, **kwargs)
            entered.set()
            await release.wait()

        monkeypatch.setattr(_document_queries, "replace_document_snapshot", gated)
        task = asyncio.create_task(
            finish(SqlAlchemyDocumentFinalization(sessions), document, FAILURE)
        )
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await current(sessions, document)).status is DocumentStatus.FAILED

    asyncio.run(run())


def test_real_pipeline_concurrent_resume_and_restart_with_committed_chunks(context):
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from sqlalchemy import select

    from nexus.composition.document_worker import _processor
    from nexus.config.document_worker_settings import DocumentWorkerSettings
    from nexus.documents.application.process_document import ProcessDocument
    from nexus.documents.ports.processing import DocumentProcessingRequested
    from nexus.files.ports import (
        ObjectStorageAlreadyExistsError,
        StoredObjectProperties,
    )
    from nexus.infrastructure.persistence.document_dispatch import (
        SqlAlchemyDocumentDispatchPersistence,
    )
    from nexus.infrastructure.persistence.models.document import (
        Document as DocumentModel,
    )
    from nexus.infrastructure.persistence.models.document_processing_request import (
        DocumentProcessingRequest,
    )
    from nexus.infrastructure.persistence.models.file import File as FileModel

    engine, sessions, document, _ = context
    request_id = uuid4()
    source_bytes = b"Example\n" * 5 + b"ok"
    with Session(engine) as session:
        file = session.scalar(select(FileModel))
        file.original_name = "example.txt"
        file.mime_type = "text/plain"
        model = session.scalar(select(DocumentModel))
        session.add(
            DocumentProcessingRequest(
                public_id=request_id,
                organization_id=model.organization_id,
                source_file_id=model.source_file_id,
                document_id=model.id,
                source_entity_tag="verified-etag",
                expected_size_bytes=42,
                created_at=document.created_at,
            )
        )
        source_key = file.storage_key
        session.commit()

    class Storage:
        def __init__(self):
            self.objects = {source_key: source_bytes}
            self.source_reads = 0

        async def get_object_properties(self, *, storage_key):
            return StoredObjectProperties(
                "verified-etag", len(self.objects[storage_key]), {}
            )

        async def stream_object(self, *, storage_key, expected_entity_tag=None):
            if storage_key == source_key:
                self.source_reads += 1
            yield self.objects[storage_key]

        async def create_object(self, *, storage_key, content):
            data = b"".join([piece async for piece in content])
            if storage_key in self.objects:
                raise ObjectStorageAlreadyExistsError()
            self.objects[storage_key] = data

    async def run():
        storage = Storage()
        documents = SqlAlchemyDocumentPersistence(sessions)
        chunks = SqlAlchemyDocumentChunkPersistence(sessions)
        finalizer = SqlAlchemyDocumentFinalization(sessions)
        requests = SqlAlchemyDocumentDispatchPersistence(sessions)
        settings = DocumentWorkerSettings(
            database_url="postgresql://test:test@localhost/test",
            azure_service_bus_fully_qualified_namespace="nexus.servicebus.windows.net",
            document_processing_version="pipeline-v1",
        )
        processor = _processor(
            settings,
            sessions,
            requests,
            documents,
            chunks,
            finalizer,
            storage,
            AsyncMock(),
        )
        handler = ProcessDocument(
            requests=requests,
            documents=documents,
            chunks=chunks,
            finalizer=finalizer,
            processor=processor,
            processing_version="pipeline-v1",
        )
        message = DocumentProcessingRequested(
            request_id, document.organization_public_id, document.public_id
        )
        outcomes = await asyncio.gather(
            handler.execute(message), handler.execute(message)
        )
        assert all(outcome.outcome is ProcessingOutcome.SUCCESS for outcome in outcomes)
        stored = await current(sessions, document)
        assert stored.status is DocumentStatus.COMPLETED
        result = await chunks.get_chunk_set(
            organization_public_id=document.organization_public_id,
            document_public_id=document.public_id,
        )
        assert result is not None and all(chunk.text.strip() for chunk in result.chunks)
        assert len(storage.objects) == 2
        reads = storage.source_reads
        assert (await handler.execute(message)).outcome is ProcessingOutcome.SUCCESS
        assert storage.source_reads == reads
        # Explicit reprocessing preserves committed history and admits the current recipe.
        from datetime import UTC, datetime

        from nexus.infrastructure.persistence.document_reprocessing import (
            SqlAlchemyDocumentReprocessing,
        )

        generation = await SqlAlchemyDocumentReprocessing(sessions).create_generation(
            organization_public_id=document.organization_public_id,
            source_file_public_id=document.source_file_public_id,
            expected_document_public_id=document.public_id,
            at=datetime.now(UTC),
        )
        with Session(engine) as session:
            next_id = session.scalar(
                select(DocumentProcessingRequest.public_id)
                .order_by(DocumentProcessingRequest.id.desc())
                .limit(1)
            )
        next_settings = settings.model_copy(
            update={"document_processing_version": "next-recipe"}
        )
        next_processor = _processor(
            next_settings,
            sessions,
            requests,
            documents,
            chunks,
            finalizer,
            storage,
            AsyncMock(),
        )
        next_handler = ProcessDocument(
            requests=requests,
            documents=documents,
            chunks=chunks,
            finalizer=finalizer,
            processor=next_processor,
            processing_version="next-recipe",
        )
        next_message = DocumentProcessingRequested(
            next_id, generation.organization_public_id, generation.public_id
        )
        assert (
            await next_handler.execute(next_message)
        ).outcome is ProcessingOutcome.SUCCESS
        next_document = await current(sessions, generation)
        assert next_document.status is DocumentStatus.COMPLETED
        assert next_document.processing_version == "next-recipe"
        assert await current(sessions, document) == stored
        assert (
            await chunks.get_chunk_set(
                organization_public_id=document.organization_public_id,
                document_public_id=document.public_id,
            )
            == result
        )
        assert len(storage.objects) == 2

    asyncio.run(run())
