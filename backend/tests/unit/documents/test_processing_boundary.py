import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nexus.documents.application.dispatch_processing import DispatchDocumentProcessing
from nexus.documents.application.process_document import ProcessDocument
from nexus.documents.domain import Document
from nexus.documents.ports.dispatch import DispatchLease
from nexus.documents.ports.persistence import DocumentConflictError
from nexus.documents.ports.processing import (
    DocumentProcessingRequested,
    ProcessingRequestRejected,
)


def message():
    return DocumentProcessingRequested(uuid4(), uuid4(), uuid4())


@pytest.mark.parametrize("version", [True, 1.0, 0, 2, "1", None])
def test_version_strict(version):
    with pytest.raises(ValueError):
        replace(message(), schema_version=version)


@pytest.mark.parametrize(
    "field", ["request_public_id", "organization_public_id", "document_public_id"]
)
def test_identity_nonzero(field):
    from uuid import UUID

    with pytest.raises(ValueError):
        replace(message(), **{field: UUID(int=0)})


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("private transport text"), TimeoutError()]
)
def test_dispatch_ack_only_after_send(failure):
    async def run():
        lease = DispatchLease(message(), uuid4(), 1)
        persistence = AsyncMock()
        persistence.claim.return_value = [lease]
        publisher = AsyncMock()
        publisher.publish.side_effect = failure
        dispatcher = DispatchDocumentProcessing(
            persistence=persistence, publisher=publisher
        )
        assert await dispatcher.dispatch_once() == 1
        if failure is None:
            persistence.acknowledge.assert_awaited_once_with(lease)
            persistence.retry.assert_not_awaited()
        else:
            persistence.acknowledge.assert_not_awaited()
            persistence.retry.assert_awaited_once_with(lease, delay_seconds=2)

    asyncio.run(run())


def test_dispatch_bounded_and_timeout():
    async def run():
        store = AsyncMock()
        store.claim.return_value = [
            DispatchLease(message(), uuid4(), 100) for _ in range(2)
        ]
        active = 0
        peak = 0

        class Publisher:
            async def publish(self, message):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    await asyncio.Event().wait()
                finally:
                    active -= 1

        dispatcher = DispatchDocumentProcessing(
            persistence=store, publisher=Publisher(), send_timeout_seconds=1
        )
        await dispatcher.dispatch_once()
        assert peak == 2 and active == 0
        assert store.retry.await_count == 2
        assert all(
            call.kwargs["delay_seconds"] == 60 for call in store.retry.await_args_list
        )
        store.acknowledge.assert_not_awaited()

    asyncio.run(run())


def test_ack_failure_and_cancellation_never_mark_or_clear_unsent():
    async def run():
        store = AsyncMock()
        lease = DispatchLease(message(), uuid4(), 1)
        store.claim.return_value = [lease]
        store.acknowledge.side_effect = RuntimeError()
        publisher = AsyncMock()
        dispatcher = DispatchDocumentProcessing(persistence=store, publisher=publisher)
        with pytest.raises(ExceptionGroup):
            await dispatcher.dispatch_once()
        store.retry.assert_not_awaited()
        publisher.publish.side_effect = asyncio.CancelledError()
        await dispatcher.dispatch_once()
        assert store.acknowledge.await_count == 1
        store.retry.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome",
    [
        "missing",
        "mismatch",
        "conflict_processing",
        "conflict_queued",
        "processor_failure",
    ],
)
def test_claim_failure_paths(outcome):
    async def run():
        event = message()
        doc = Document(
            public_id=event.document_public_id,
            organization_public_id=event.organization_public_id,
            source_file_public_id=uuid4(),
            created_at=datetime.now(UTC),
        )
        started = doc.start_processing(at=datetime.now(UTC), processing_version="v1")
        requests = AsyncMock()
        requests.matches.return_value = outcome != "mismatch"
        persistence = AsyncMock()
        persistence.get_document.return_value = None if outcome == "missing" else doc
        processor = AsyncMock()
        handler = ProcessDocument(
            requests=requests,
            documents=persistence,
            processor=processor,
            processing_version="v1",
        )
        if outcome.startswith("conflict"):
            persistence.update_document.side_effect = DocumentConflictError()
            persistence.get_document.side_effect = [
                doc,
                started if outcome == "conflict_processing" else doc,
            ]
        if outcome == "processor_failure":
            processor.process.side_effect = RuntimeError()
        error = (
            ProcessingRequestRejected
            if outcome in {"missing", "mismatch"}
            else DocumentConflictError
            if outcome == "conflict_queued"
            else RuntimeError
        )
        if outcome == "conflict_processing":
            await handler.execute(event)
        else:
            with pytest.raises(error):
                await handler.execute(event)
        assert processor.process.await_count == (
            1 if outcome == "processor_failure" else 0
        )

    asyncio.run(run())


def test_fatal_publication_stops_poll_without_retry():
    from nexus.documents.ports.dispatch import DocumentPublicationError

    async def run():
        store, publisher = AsyncMock(), AsyncMock()
        store.claim.return_value = [DispatchLease(message(), uuid4(), 1)]
        publisher.publish.side_effect = DocumentPublicationError()
        with pytest.raises(ExceptionGroup):
            await DispatchDocumentProcessing(
                persistence=store, publisher=publisher
            ).run(asyncio.Event())
        store.retry.assert_not_awaited()
        store.acknowledge.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("status", ["processing", "completed", "failed"])
def test_nonqueued_documents_never_invoke_processor(status):

    async def run():
        event = message()
        at = datetime.now(UTC)
        doc = Document(
            public_id=event.document_public_id,
            organization_public_id=event.organization_public_id,
            source_file_public_id=uuid4(),
            created_at=at,
        ).start_processing(at=at, processing_version="v1")
        if status == "completed":
            doc = doc.record_extractor_version(extractor_version="test").complete(at=at)
        elif status == "failed":
            doc = doc.fail(at=at, code="TEST", safe_message="safe")
        requests, persistence, processor = AsyncMock(), AsyncMock(), AsyncMock()
        requests.matches.return_value = True
        persistence.get_document.return_value = doc
        await ProcessDocument(
            requests=requests,
            documents=persistence,
            processor=processor,
            processing_version="v1",
        ).execute(event)
        persistence.update_document.assert_not_awaited()
        processor.process.assert_not_awaited()

    asyncio.run(run())
