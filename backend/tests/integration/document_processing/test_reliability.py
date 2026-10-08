import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from tests.integration.document_processing.conftest import (
    TXT,
    admit,
    chunks,
    document,
    handler,
    pipeline,
)

from nexus.documents.domain import DocumentStatus
from nexus.documents.ports.processing import (
    ProcessingOutcome,
    ProcessingRequestRejected,
)
from nexus.files.ports.storage import ObjectStorageError, ObjectStorageFailure


def test_duplicate_and_concurrent_delivery_converge(run_case, monkeypatch):
    async def run(engine, sessions, storage, client):
        _, message = await admit(engine, sessions, storage, TXT)
        original = storage.stream_object
        arrived = 0
        both = asyncio.Event()

        async def stream(**kwargs):
            nonlocal arrived
            if kwargs["storage_key"].startswith("files/"):
                arrived += 1
                if arrived == 2:
                    both.set()
                await both.wait()
            async for part in original(**kwargs):
                yield part

        monkeypatch.setattr(storage, "stream_object", stream)
        coordinator = handler(sessions, pipeline(sessions, storage))
        async with asyncio.timeout(20):
            outcomes = await asyncio.gather(
                coordinator.execute(message), coordinator.execute(message)
            )
        assert all(r.outcome is ProcessingOutcome.SUCCESS for r in outcomes)
        before = await chunks(sessions, message)
        assert (await document(sessions, message)).status is DocumentStatus.COMPLETED
        assert (await coordinator.execute(message)).outcome is ProcessingOutcome.SUCCESS
        assert await chunks(sessions, message) == before
        assert arrived == 2
        assert (
            len([b async for b in client.list_blobs(name_starts_with="documents/")])
            == 1
        )

    run_case(run)


def test_different_documents_progress_independently(run_case, monkeypatch):
    async def run(engine, sessions, storage, client):
        first_file, first = await admit(engine, sessions, storage, TXT)
        _, second = await admit(engine, sessions, storage, b"Independent document")
        original = storage.stream_object
        entered, release = asyncio.Event(), asyncio.Event()

        async def stream(**kwargs):
            if kwargs["storage_key"] == first_file.storage_key:
                entered.set()
                await release.wait()
            async for part in original(**kwargs):
                yield part

        monkeypatch.setattr(storage, "stream_object", stream)
        coordinator = handler(sessions, pipeline(sessions, storage))
        async with asyncio.timeout(20):
            task = asyncio.create_task(coordinator.execute(first))
            try:
                await entered.wait()
                assert (
                    await coordinator.execute(second)
                ).outcome is ProcessingOutcome.SUCCESS
                assert not task.done()
            finally:
                release.set()
                await task
        assert (await document(sessions, first)).status is DocumentStatus.COMPLETED
        assert (await document(sessions, second)).status is DocumentStatus.COMPLETED

    run_case(run)


def test_transient_storage_failure_redelivery_completes(run_case, monkeypatch):
    async def run(engine, sessions, storage, client):
        _, message = await admit(engine, sessions, storage, TXT)
        original = storage.get_object_properties
        failing = True

        async def properties(**kwargs):
            nonlocal failing
            if failing:
                failing = False
                raise ObjectStorageError(reason=ObjectStorageFailure.TRANSIENT)
            return await original(**kwargs)

        monkeypatch.setattr(storage, "get_object_properties", properties)
        coordinator = handler(sessions, pipeline(sessions, storage))
        assert (
            await coordinator.execute(message)
        ).outcome is ProcessingOutcome.RETRYABLE
        assert (await document(sessions, message)).status is DocumentStatus.PROCESSING
        assert await chunks(sessions, message) is None
        assert (await coordinator.execute(message)).outcome is ProcessingOutcome.SUCCESS
        assert (await document(sessions, message)).status is DocumentStatus.COMPLETED

    run_case(run)


def test_restart_finalizes_committed_chunks_without_source_access(
    run_case, monkeypatch
):
    async def run(engine, sessions, storage, client):
        _, message = await admit(engine, sessions, storage, TXT)
        # Simulate process interruption after persistence, before successful finalization.
        processor = pipeline(
            sessions,
            storage,
            finalizer=AsyncMock(finalize=AsyncMock(side_effect=asyncio.CancelledError)),
        )
        with pytest.raises(asyncio.CancelledError):
            await handler(sessions, processor).execute(message)
        committed = await chunks(sessions, message)
        assert committed is not None
        assert (await document(sessions, message)).status is DocumentStatus.PROCESSING
        monkeypatch.setattr(
            storage,
            "get_object_properties",
            AsyncMock(side_effect=AssertionError("Source must not reopen")),
        )
        assert (
            await handler(sessions, pipeline(sessions, storage)).execute(message)
        ).outcome is ProcessingOutcome.SUCCESS
        assert await chunks(sessions, message) == committed
        assert (await document(sessions, message)).status is DocumentStatus.COMPLETED

    run_case(run)


def test_foreign_and_missing_identities_reject_without_io_or_mutation(
    run_case, monkeypatch
):
    async def run(engine, sessions, storage, client):
        _, first = await admit(engine, sessions, storage, TXT)
        _, foreign = await admit(engine, sessions, storage, TXT)
        snapshots = [await document(sessions, m) for m in (first, foreign)]
        storage_read = AsyncMock(
            side_effect=AssertionError("Rejected request must not access storage")
        )
        monkeypatch.setattr(storage, "get_object_properties", storage_read)
        coordinator = handler(sessions, pipeline(sessions, storage))
        errors = []
        for invalid in (
            replace(first, organization_public_id=foreign.organization_public_id),
            replace(first, document_public_id=foreign.document_public_id),
            replace(first, request_public_id=foreign.request_public_id),
            replace(first, organization_public_id=uuid4()),
            replace(first, document_public_id=uuid4()),
            replace(first, request_public_id=uuid4()),
        ):
            with pytest.raises(ProcessingRequestRejected) as exc:
                await coordinator.execute(invalid)
            errors.append(str(exc.value))
        assert len(set(errors)) == 1
        assert [await document(sessions, m) for m in (first, foreign)] == snapshots
        assert all([await chunks(sessions, m) is None for m in (first, foreign)])
        storage_read.assert_not_called()

    run_case(run)
