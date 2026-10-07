"""Document process composition; consumption requires a real processor."""

from contextlib import AsyncExitStack
from dataclasses import dataclass
from uuid import UUID

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.identity.aio import ManagedIdentityCredential
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient
from azure.storage.blob.aio import BlobServiceClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.composition.storage import AZURE_BLOB_CLIENT_OPTIONS
from nexus.config.document_worker_settings import DocumentWorkerSettings
from nexus.documents.application.dispatch_processing import DispatchDocumentProcessing
from nexus.documents.application.document_processor import ProcessDocumentPipeline
from nexus.documents.application.extract_document import ExtractDocument
from nexus.documents.application.normalize_document import NormalizeDocument
from nexus.documents.application.open_source import OpenDocumentSource
from nexus.documents.application.process_document import ProcessDocument
from nexus.documents.application.segment_document import SegmentDocument
from nexus.documents.application.write_normalized_artifact import (
    WriteNormalizedArtifact,
)
from nexus.documents.ports.extraction import PdfPageOcr
from nexus.documents.ports.processing import DocumentProcessor
from nexus.files.ports import ObjectStorage
from nexus.infrastructure.extraction.azure_document_intelligence import (
    AZURE_READ_API_VERSION,
    AzureDocumentIntelligenceOcr,
)
from nexus.infrastructure.extraction.pdf import PdfDocumentExtractor
from nexus.infrastructure.extraction.pdf_ocr import PdfWithOcrDocumentExtractor
from nexus.infrastructure.extraction.text import (
    MarkdownDocumentExtractor,
    TxtDocumentExtractor,
)
from nexus.infrastructure.messaging.azure_service_bus_document_processing import (
    AzureServiceBusDocumentPublisher,
    AzureServiceBusDocumentWorker,
)
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusQueuePublisher,
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
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence
from nexus.infrastructure.persistence.session import build_database
from nexus.infrastructure.storage import AzureBlobObjectStorage


@dataclass
class DocumentWorkerComposition:
    dispatcher: DispatchDocumentProcessing
    worker: AzureServiceBusDocumentWorker | None
    resources: AsyncExitStack

    async def close(self) -> None:
        await self.resources.aclose()


async def build_document_worker_composition(
    settings: DocumentWorkerSettings,
    *,
    consume: bool = False,
    processor: DocumentProcessor | None = None,
) -> DocumentWorkerComposition:
    if consume and processor is None:
        settings.validate_consumer()
    resources = AsyncExitStack()
    try:
        client_id = settings.azure_service_bus_managed_identity_client_id
        credential = (
            ManagedIdentityCredential(client_id=str(client_id))
            if client_id
            else ManagedIdentityCredential()
        )
        resources.push_async_callback(credential.close)
        client = ServiceBusClient(
            settings.azure_service_bus_fully_qualified_namespace, credential=credential
        )
        resources.push_async_callback(client.close)
        storage = None
        ocr = None
        if consume and processor is None:
            storage_credential = _provider_credential(
                settings.azure_storage_managed_identity_client_id,
                client_id,
                credential,
                resources,
            )
            blob = BlobServiceClient(
                account_url=str(settings.azure_storage_account_url),
                credential=storage_credential,
                **AZURE_BLOB_CLIENT_OPTIONS,
            )
            resources.push_async_callback(blob.close)
            assert settings.azure_storage_container is not None
            storage = AzureBlobObjectStorage(
                blob.get_container_client(settings.azure_storage_container)
            )
            ocr_credential = _provider_credential(
                settings.azure_document_intelligence_managed_identity_client_id,
                client_id,
                credential,
                resources,
            )
            read = DocumentIntelligenceClient(
                endpoint=str(settings.azure_document_intelligence_endpoint),
                credential=ocr_credential,
                api_version=AZURE_READ_API_VERSION,
            )
            resources.push_async_callback(read.close)
            ocr = AzureDocumentIntelligenceOcr(
                read, concurrency=settings.document_worker_concurrency
            )
        return _compose(
            settings,
            client,
            resources,
            processor if consume else None,
            storage=storage,
            ocr=ocr,
        )
    except BaseException:
        await resources.aclose()
        raise


def _compose(
    settings: DocumentWorkerSettings,
    client: ServiceBusClient,
    resources: AsyncExitStack,
    processor: DocumentProcessor | None = None,
    *,
    storage: ObjectStorage | None = None,
    ocr: PdfPageOcr | None = None,
) -> DocumentWorkerComposition:
    database = build_database(
        settings.database_url,
        pool_size=settings.document_database_pool_size,
        max_overflow=0,
    )
    resources.push_async_callback(database.dispose)
    requests = SqlAlchemyDocumentDispatchPersistence(database.session_factory)
    service_bus_publisher = AzureServiceBusQueuePublisher(client)
    dispatcher = DispatchDocumentProcessing(
        persistence=requests,
        publisher=AzureServiceBusDocumentPublisher(
            service_bus_publisher, settings.azure_service_bus_document_queue_name
        ),
        concurrency=settings.document_dispatch_concurrency,
        lease_seconds=settings.document_dispatch_lease_seconds,
        send_timeout_seconds=settings.document_dispatch_send_timeout_seconds,
        poll_seconds=settings.document_dispatch_poll_seconds,
    )
    worker = None
    documents = SqlAlchemyDocumentPersistence(database.session_factory)
    chunks = SqlAlchemyDocumentChunkPersistence(database.session_factory)
    finalizer = SqlAlchemyDocumentFinalization(database.session_factory)
    if storage is not None and ocr is not None:
        processor = _processor(
            settings,
            database.session_factory,
            requests,
            documents,
            chunks,
            finalizer,
            storage,
            ocr,
        )
    if processor is not None:
        renewer = AutoLockRenewer(
            max_lock_renewal_duration=settings.document_worker_max_lock_renewal_seconds
        )
        resources.push_async_callback(renewer.close)
        worker = AzureServiceBusDocumentWorker(
            client=client,
            queue_name=settings.azure_service_bus_document_queue_name,
            handler=ProcessDocument(
                requests=requests,
                documents=documents,
                chunks=chunks,
                finalizer=finalizer,
                processor=processor,
                processing_version=settings.document_processing_version,
                attempt_timeout_seconds=settings.document_attempt_timeout_seconds,
            ),
            auto_lock_renewer=renewer,
            concurrency=settings.document_worker_concurrency,
            max_delivery_count=settings.document_worker_max_delivery_count,
        )
    return DocumentWorkerComposition(dispatcher, worker, resources)


def _provider_credential(
    client_id: UUID | None,
    shared_id: UUID | None,
    shared: ManagedIdentityCredential,
    resources: AsyncExitStack,
) -> ManagedIdentityCredential:
    if client_id is None or client_id == shared_id:
        return shared
    credential = ManagedIdentityCredential(client_id=str(client_id))
    resources.push_async_callback(credential.close)
    return credential


def _processor(
    settings: DocumentWorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    requests: SqlAlchemyDocumentDispatchPersistence,
    documents: SqlAlchemyDocumentPersistence,
    chunks: SqlAlchemyDocumentChunkPersistence,
    finalizer: SqlAlchemyDocumentFinalization,
    storage: ObjectStorage,
    ocr: PdfPageOcr,
) -> DocumentProcessor:
    source = OpenDocumentSource(
        requests=requests,
        files=SqlAlchemyFilePersistence(sessions),
        storage=storage,
        max_size_bytes=settings.file_upload_max_size_bytes,
    )
    extraction = ExtractDocument(
        source=source,
        txt=TxtDocumentExtractor(),
        markdown=MarkdownDocumentExtractor(),
        pdf=PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), ocr),
    )
    return ProcessDocumentPipeline(
        documents=documents,
        chunks=chunks,
        finalizer=finalizer,
        extraction=extraction,
        normalization=NormalizeDocument(),
        artifacts=WriteNormalizedArtifact(storage),
        segmentation=SegmentDocument(),
        processing_version=settings.document_processing_version,
    )
