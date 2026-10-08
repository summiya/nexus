"""Real PostgreSQL leasing and single-winner Document initiation."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from tests.integration.persistence.test_document_initiation import _scan, _seed_file

from nexus.documents.application.document_processing_handler import (
    DocumentProcessingHandler,
)
from nexus.documents.domain import DocumentStatus
from nexus.documents.ports.processing import ProcessingRequestRejected
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_dispatch import (
    SqlAlchemyDocumentDispatchPersistence,
)
from nexus.infrastructure.persistence.document_finalization import (
    SqlAlchemyDocumentFinalization,
)
from nexus.infrastructure.persistence.models import DocumentProcessingRequest


@pytest.fixture
def prepared(migrated_database):
    config, engine = migrated_database
    command.upgrade(config, "head")
    return engine


async def _seed(engine, factory, count=1):
    for _ in range(count):
        await _scan(factory, _seed_file(engine))
    return SqlAlchemyDocumentDispatchPersistence(factory)


def test_competing_dispatchers_and_stale_token(
    prepared, persistence_async_session_factory
):
    async def run():
        store = await _seed(prepared, persistence_async_session_factory, 3)
        batches = await asyncio.gather(
            store.claim(limit=2, lease_seconds=60),
            store.claim(limit=2, lease_seconds=60),
        )
        leases = [lease for batch in batches for lease in batch]
        assert len(leases) == 3
        assert len({lease.message.request_public_id for lease in leases}) == 3
        assert await store.claim(limit=2, lease_seconds=60) == []
        old = leases[0]
        with Session(prepared) as session:
            session.execute(
                update(DocumentProcessingRequest)
                .where(
                    DocumentProcessingRequest.public_id == old.message.request_public_id
                )
                .values(dispatch_lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            session.commit()
        new = (await store.claim(limit=1, lease_seconds=60))[0]
        assert (
            new.message == old.message and new.token != old.token and new.attempt == 2
        )
        await store.acknowledge(old)
        await store.retry(old, delay_seconds=0)
        assert await store.claim(limit=1, lease_seconds=60) == []
        await store.acknowledge(new)
        with Session(prepared) as session:
            row = session.scalar(
                select(DocumentProcessingRequest).where(
                    DocumentProcessingRequest.public_id == new.message.request_public_id
                )
            )
            assert row.dispatched_at is not None
            assert row.dispatch_lease_token is None
        assert await store.matches(new.message)

    asyncio.run(run())


def test_retry_preserves_identity_and_delay(
    prepared, persistence_async_session_factory
):
    async def run():
        store = await _seed(prepared, persistence_async_session_factory)
        lease = (await store.claim(limit=1, lease_seconds=60))[0]
        await store.retry(lease, delay_seconds=60)
        assert await store.claim(limit=1, lease_seconds=60) == []
        with Session(prepared) as session:
            row = session.scalar(select(DocumentProcessingRequest))
            assert row.dispatched_at is None
            row.dispatch_next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        again = (await store.claim(limit=1, lease_seconds=60))[0]
        assert again.message == lease.message

    asyncio.run(run())


def test_single_start_snapshot_and_tenant_safe_resume(
    prepared, persistence_async_session_factory
):
    async def run():
        store = await _seed(prepared, persistence_async_session_factory)
        message = (await store.claim(limit=1, lease_seconds=60))[0].message
        calls = []

        class Processor:
            async def process(self, *, document, request):
                calls.append(document)
                await asyncio.sleep(0.02)

        documents = SqlAlchemyDocumentPersistence(persistence_async_session_factory)
        handler = DocumentProcessingHandler(
            requests=store,
            finalizer=SqlAlchemyDocumentFinalization(persistence_async_session_factory),
            documents=documents,
            processor=Processor(),
            processing_version="test-v1",
        )
        for invalid in (
            replace(message, organization_public_id=uuid4()),
            replace(message, request_public_id=uuid4()),
            replace(message, document_public_id=uuid4()),
        ):
            with pytest.raises(ProcessingRequestRejected, match="request rejected"):
                await handler.execute(invalid)
        assert (
            await documents.get_document(
                organization_public_id=message.organization_public_id,
                document_public_id=message.document_public_id,
            )
        ).status == DocumentStatus.QUEUED
        # The request has not been marked dispatched: receive-before-ack must work.
        await asyncio.gather(*(handler.execute(message) for _ in range(8)))
        await handler.execute(message)
        assert len(calls) == 9
        assert all(document == calls[0] for document in calls)
        assert calls[0].status == DocumentStatus.PROCESSING

    asyncio.run(run())


def test_different_documents_run_concurrently_and_interrupted_processing_resumes(
    prepared, persistence_async_session_factory
):
    async def run():
        store = await _seed(prepared, persistence_async_session_factory, 2)
        messages = [
            lease.message for lease in await store.claim(limit=2, lease_seconds=60)
        ]
        started = asyncio.Event()
        calls = []

        class Processor:
            async def process(self, *, document, request):
                calls.append(document)
                if len(calls) == 2:
                    started.set()
                if len(calls) <= 2:
                    await asyncio.Event().wait()

        handler = DocumentProcessingHandler(
            requests=store,
            finalizer=SqlAlchemyDocumentFinalization(persistence_async_session_factory),
            documents=SqlAlchemyDocumentPersistence(persistence_async_session_factory),
            processor=Processor(),
            processing_version="test-v1",
        )
        tasks = [asyncio.create_task(handler.execute(message)) for message in messages]
        await asyncio.wait_for(started.wait(), timeout=5)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for message in messages:
            await handler.execute(message)
        assert len(calls) == 4
        assert {d.public_id: d for d in calls[:2]} == {
            d.public_id: d for d in calls[2:]
        }

    asyncio.run(run())


def test_foreign_request_document_pair_is_rejected_without_mutation(
    prepared, persistence_async_session_factory
):
    async def run():
        store = await _seed(prepared, persistence_async_session_factory, 2)
        first, foreign = [
            lease.message for lease in await store.claim(limit=2, lease_seconds=60)
        ]
        processor = AsyncMock()
        documents = SqlAlchemyDocumentPersistence(persistence_async_session_factory)
        handler = DocumentProcessingHandler(
            requests=store,
            finalizer=SqlAlchemyDocumentFinalization(persistence_async_session_factory),
            documents=documents,
            processor=processor,
            processing_version="v1",
        )
        for invalid in (
            replace(first, organization_public_id=foreign.organization_public_id),
            replace(first, document_public_id=foreign.document_public_id),
            replace(foreign, organization_public_id=first.organization_public_id),
        ):
            with pytest.raises(ProcessingRequestRejected):
                await handler.execute(invalid)
        processor.process.assert_not_awaited()
        for message in (first, foreign):
            document = await documents.get_document(
                organization_public_id=message.organization_public_id,
                document_public_id=message.document_public_id,
            )
            assert document.status == DocumentStatus.QUEUED

    asyncio.run(run())
