"""Local infrastructure and existing capability assembly for DP-12 proofs."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from azure.servicebus.amqp import AmqpMessageBodyType
from sqlalchemy import update
from sqlalchemy.orm import Session
from tests.integration.persistence.conftest import (  # noqa: F401
    migrated_database,
    persistence_async_engine,
    persistence_async_session_factory,
)
from tests.integration.persistence.test_document_initiation import NOW, _seed_file
from tests.integration.storage.test_azure_blob_storage import (
    _with_isolated_storage,
    byte_stream,
)

from nexus.documents.application.dispatch_processing import DispatchDocumentProcessing
from nexus.documents.application.document_processing_handler import (
    DocumentProcessingHandler,
)
from nexus.documents.application.document_processing_pipeline import (
    DocumentProcessingPipeline,
)
from nexus.documents.application.extract_document import ExtractDocument
from nexus.documents.application.normalize_document import NormalizeDocument
from nexus.documents.application.open_source import OpenDocumentSource
from nexus.documents.application.segment_document import SegmentDocument
from nexus.documents.application.write_normalized_artifact import (
    WriteNormalizedArtifact,
)
from nexus.documents.domain import ExtractedBlockKind
from nexus.documents.ports.extraction import OcrBlock, OcrPage
from nexus.infrastructure.extraction.pdf import PdfDocumentExtractor
from nexus.infrastructure.extraction.pdf_ocr import PdfWithOcrDocumentExtractor
from nexus.infrastructure.extraction.text import (
    MarkdownDocumentExtractor,
    TxtDocumentExtractor,
)
from nexus.infrastructure.messaging._document_processing_message import (
    decode_document_message,
    encode_document_message,
)
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_chunk import (
    SqlAlchemyDocumentChunkPersistence,
)
from nexus.infrastructure.persistence.document_dispatch import (
    SqlAlchemyDocumentDispatchPersistence,
)
from nexus.infrastructure.persistence.document_finalization import (
    SqlAlchemyDocumentFinalization,
)
from nexus.infrastructure.persistence.document_initiation import (
    SqlAlchemyDocumentInitiationPersistence,
)
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence
from nexus.infrastructure.persistence.models import File as FileModel

PDFS = Path(__file__).resolve().parents[2] / "fixtures" / "extraction"
LONG_TEXT = "Café Ω " * 40
TXT = f"First paragraph\n\nSecond paragraph\n\n{LONG_TEXT}\n".encode()
MARKDOWN = f"# Main\n\nIntro\n\n## Detail\n\n- First\n- Second\n\n> Quote\n\n```python\nx = 1\n```\n\n<div>raw</div>\n\n{LONG_TEXT}\n".encode()


class DeterministicOcr:
    def __init__(self):
        self.calls = []

    async def extract_pages(self, pdf_bytes, *, page_numbers):
        self.calls.append(page_numbers)
        return tuple(
            OcrPage(page, (OcrBlock(ExtractedBlockKind.TEXT, f"OCR page {page}"),))
            for page in page_numbers
        )


class CapturingPublisher:
    def __init__(self):
        self.messages = []

    async def publish(self, message):
        body = encode_document_message(message)
        self.messages.append(
            decode_document_message(
                SimpleNamespace(
                    body_type=AmqpMessageBodyType.DATA,
                    body=body,
                )
            )
        )


@pytest.fixture
def run_case(migrated_database, persistence_async_session_factory, monkeypatch):  # noqa: F811 - imported pytest fixtures
    config, engine = migrated_database
    command.upgrade(config, "head")
    # Compose uses the Docker hostname; direct CI tests use the existing localhost default.
    if "NEXUS_TEST_AZURITE_CONNECTION_STRING" not in os.environ:
        connection = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if connection:
            monkeypatch.setenv("NEXUS_TEST_AZURITE_CONNECTION_STRING", connection)

    def run(scenario):
        async def with_storage(storage, client):
            await scenario(engine, persistence_async_session_factory, storage, client)

        asyncio.run(_with_isolated_storage(with_storage))

    return run


async def dispatch(sessions):
    publisher = CapturingPublisher()
    requests = SqlAlchemyDocumentDispatchPersistence(sessions)
    count = await DispatchDocumentProcessing(
        persistence=requests,
        publisher=publisher,
    ).dispatch_once()
    assert count == len(publisher.messages)
    assert (
        await DispatchDocumentProcessing(
            persistence=requests,
            publisher=publisher,
        ).dispatch_once()
        == 0
    )
    return publisher.messages


async def admit(engine, sessions, storage, data, name="quality.txt", mime="text/plain"):
    file = _seed_file(engine, name=name)
    with Session(engine) as session:
        session.execute(
            update(FileModel)
            .where(FileModel.public_id == file.public_id)
            .values(
                size_bytes=len(data),
                mime_type=mime,
            )
        )
        session.commit()
    await storage.create_object(storage_key=file.storage_key, content=byte_stream(data))
    properties = await storage.get_object_properties(storage_key=file.storage_key)
    await SqlAlchemyDocumentInitiationPersistence(sessions).apply_clean_scan(
        storage_key=file.storage_key,
        source_entity_tag=properties.entity_tag,
        expected_size_bytes=len(data),
        at=NOW,
    )
    available = await SqlAlchemyFilePersistence(sessions).get_file(
        organization_public_id=file.organization_public_id,
        file_public_id=file.public_id,
    )
    assert available.storage_status.value == "available"
    messages = await dispatch(sessions)
    if not messages:
        return available, None
    assert len(messages) == 1
    queued = await document(sessions, messages[0])
    assert queued.status.value == "queued"
    facts = await SqlAlchemyDocumentDispatchPersistence(sessions).get_source_facts(
        messages[0]
    )
    assert facts.source_file_public_id == available.public_id
    assert facts.expected_size_bytes == len(data)
    assert facts.source_entity_tag == properties.entity_tag
    return available, messages[0]


def pipeline(
    sessions,
    storage,
    *,
    ocr=None,
    recipe="dp12-v1",
    max_bytes=1024 * 1024,
    chunk_bytes=64,
    finalizer=None,
):
    requests = SqlAlchemyDocumentDispatchPersistence(sessions)
    documents = SqlAlchemyDocumentPersistence(sessions)
    extraction = ExtractDocument(
        source=OpenDocumentSource(
            requests=requests,
            files=SqlAlchemyFilePersistence(sessions),
            storage=storage,
            max_size_bytes=max_bytes,
        ),
        txt=TxtDocumentExtractor(),
        markdown=MarkdownDocumentExtractor(),
        pdf=PdfWithOcrDocumentExtractor(
            PdfDocumentExtractor(), ocr or DeterministicOcr()
        ),
    )
    return DocumentProcessingPipeline(
        documents=documents,
        chunks=SqlAlchemyDocumentChunkPersistence(sessions),
        finalizer=finalizer or SqlAlchemyDocumentFinalization(sessions),
        extraction=extraction,
        normalization=NormalizeDocument(),
        artifacts=WriteNormalizedArtifact(storage),
        segmentation=SegmentDocument(
            preferred_chunk_bytes=chunk_bytes, max_chunk_bytes=chunk_bytes
        ),
        processing_version=recipe,
    )


def handler(sessions, processor, *, recipe="dp12-v1", finalizer=None):
    return DocumentProcessingHandler(
        requests=SqlAlchemyDocumentDispatchPersistence(sessions),
        documents=SqlAlchemyDocumentPersistence(sessions),
        processor=processor,
        finalizer=finalizer or SqlAlchemyDocumentFinalization(sessions),
        processing_version=recipe,
    )


async def document(sessions, message):
    return await SqlAlchemyDocumentPersistence(sessions).get_document(
        organization_public_id=message.organization_public_id,
        document_public_id=message.document_public_id,
    )


async def chunks(sessions, message):
    return await SqlAlchemyDocumentChunkPersistence(sessions).get_chunk_set(
        organization_public_id=message.organization_public_id,
        document_public_id=message.document_public_id,
    )
