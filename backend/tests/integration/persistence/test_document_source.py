import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import event
from tests.integration.helpers import seed_file
from tests.integration.persistence.test_document_initiation import _scan

from nexus.documents.application.open_source import OpenDocumentSource
from nexus.documents.ports.source import DocumentSourceError
from nexus.files.ports import StoredObjectProperties
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_dispatch import (
    SqlAlchemyDocumentDispatchPersistence,
)
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence


def test_tenant_source_facts_and_stream_do_not_hold_database_connections(
    migrated_database, persistence_async_session_factory, persistence_async_engine
):
    config, engine = migrated_database
    command.upgrade(config, "head")
    checked_out = 0

    @event.listens_for(persistence_async_engine.sync_engine, "checkout")
    def checkout(*args):
        nonlocal checked_out
        checked_out += 1

    @event.listens_for(persistence_async_engine.sync_engine, "checkin")
    def checkin(*args):
        nonlocal checked_out
        checked_out -= 1

    async def run():
        files = [seed_file(engine), seed_file(engine)]
        for file in files:
            await _scan(persistence_async_session_factory, file)
        requests = SqlAlchemyDocumentDispatchPersistence(
            persistence_async_session_factory
        )
        messages = [
            lease.message for lease in await requests.claim(limit=2, lease_seconds=60)
        ]
        message, foreign = messages
        documents = SqlAlchemyDocumentPersistence(persistence_async_session_factory)
        document = await documents.get_document(
            organization_public_id=message.organization_public_id,
            document_public_id=message.document_public_id,
        )
        queued = document
        document = document.start_processing(
            at=document.created_at, processing_version="test"
        )
        await documents.update_document(expected=queued, document=document)
        facts = await requests.get_source_facts(message)
        assert facts.source_file_public_id == document.source_file_public_id
        assert (
            facts.source_entity_tag == "verified-v1" and facts.expected_size_bytes == 42
        )
        for invalid in (
            replace(message, request_public_id=uuid4()),
            replace(message, organization_public_id=foreign.organization_public_id),
            replace(message, document_public_id=foreign.document_public_id),
        ):
            assert await requests.get_source_facts(invalid) is None
        storage = AsyncMock()
        storage.get_object_properties.return_value = StoredObjectProperties(
            entity_tag="verified-v1", size_bytes=42, metadata={}
        )
        streamed_keys = []

        async def content(**kwargs):
            assert checked_out == 0
            streamed_keys.append(kwargs)
            yield b"x" * 21
            await asyncio.sleep(0)
            assert checked_out == 0
            yield b"y" * 21

        storage.stream_object = content
        capability = OpenDocumentSource(
            requests=requests,
            files=SqlAlchemyFilePersistence(persistence_async_session_factory),
            storage=storage,
            max_size_bytes=42,
        )
        async with capability.open(document=document, request=message) as source:
            assert checked_out == 0
            assert sum([len(chunk) async for chunk in source.content]) == 42
        source_file = next(
            file for file in files if file.public_id == facts.source_file_public_id
        )
        assert streamed_keys == [
            {
                "storage_key": source_file.storage_key,
                "expected_entity_tag": "verified-v1",
            }
        ]
        with pytest.raises(DocumentSourceError):
            async with capability.open(document=document, request=foreign):
                pass
        assert checked_out == 0

    asyncio.run(run())
