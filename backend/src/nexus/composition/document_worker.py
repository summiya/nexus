"""Document process composition; consumption requires a real processor."""

from contextlib import AsyncExitStack
from dataclasses import dataclass

from azure.identity.aio import ManagedIdentityCredential
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient

from nexus.config.document_worker_settings import DocumentWorkerSettings
from nexus.documents.application.dispatch_processing import DispatchDocumentProcessing
from nexus.documents.application.process_document import ProcessDocument
from nexus.documents.ports.processing import DocumentProcessor
from nexus.infrastructure.messaging.azure_service_bus_document_processing import (
    AzureServiceBusDocumentPublisher,
    AzureServiceBusDocumentWorker,
)
from nexus.infrastructure.messaging.azure_service_bus_publisher import (
    AzureServiceBusQueuePublisher,
)
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_dispatch import (
    SqlAlchemyDocumentDispatchPersistence,
)
from nexus.infrastructure.persistence.session import build_database


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
        raise ValueError("Document consumption requires a real downstream processor")
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
        return _compose(settings, client, resources, processor if consume else None)
    except BaseException:
        await resources.aclose()
        raise


def _compose(
    settings: DocumentWorkerSettings,
    client: ServiceBusClient,
    resources: AsyncExitStack,
    processor: DocumentProcessor | None = None,
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
                documents=SqlAlchemyDocumentPersistence(database.session_factory),
                processor=processor,
                processing_version=settings.document_processing_version,
            ),
            auto_lock_renewer=renewer,
            concurrency=settings.document_worker_concurrency,
        )
    return DocumentWorkerComposition(dispatcher, worker, resources)
