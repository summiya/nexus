"""Composition and lifecycle for the dedicated File completion worker."""

from __future__ import annotations

from asyncio import CancelledError
from dataclasses import dataclass
from urllib.parse import urlsplit

from azure.identity.aio import ManagedIdentityCredential
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient
from azure.storage.blob.aio import BlobServiceClient

from nexus.config.file_worker_settings import FileWorkerSettings
from nexus.files.application import ApplyMalwareScanResult, VerifyUploadCompletion
from nexus.infrastructure.messaging import AzureServiceBusUploadCompletionWorker
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence
from nexus.infrastructure.persistence.session import Database, build_database
from nexus.infrastructure.storage import (
    AzureBlobCreatedEventMapper,
    AzureMalwareScanResultMapper,
)
from nexus.infrastructure.storage.azure_blob import AzureBlobObjectStorage
from nexus.infrastructure.upload_context import AesGcmUploadContextProtector


@dataclass(frozen=True)
class FileWorkerComposition:
    """Own the dedicated worker and its Azure resources."""

    worker: AzureServiceBusUploadCompletionWorker
    malware_scan_worker: AzureServiceBusUploadCompletionWorker
    service_bus_client: ServiceBusClient
    blob_service_client: BlobServiceClient
    database: Database
    credential: ManagedIdentityCredential
    auto_lock_renewer: AutoLockRenewer

    async def close(self) -> None:
        """Release worker resources in dependency order."""

        try:
            await self.auto_lock_renewer.close()
        finally:
            try:
                await self.service_bus_client.close()
            finally:
                try:
                    await self.blob_service_client.close()
                finally:
                    try:
                        await self.database.dispose()
                    finally:
                        await self.credential.close()


async def build_file_worker_composition(
    settings: FileWorkerSettings,
) -> FileWorkerComposition:
    """Build only resources required to verify and register File uploads."""

    credential: ManagedIdentityCredential | None = None
    client: ServiceBusClient | None = None
    blob_service_client: BlobServiceClient | None = None
    database: Database | None = None
    auto_lock_renewer: AutoLockRenewer | None = None
    try:
        client_id = settings.azure_service_bus_managed_identity_client_id
        credential = (
            ManagedIdentityCredential(client_id=str(client_id))
            if client_id is not None
            else ManagedIdentityCredential()
        )
        client = ServiceBusClient(
            fully_qualified_namespace=(
                settings.azure_service_bus_fully_qualified_namespace
            ),
            credential=credential,
        )
        blob_service_client = BlobServiceClient(
            account_url=str(settings.azure_storage_account_url),
            credential=credential,
        )
        object_storage = AzureBlobObjectStorage(
            blob_service_client.get_container_client(settings.azure_storage_container)
        )
        database = build_database(
            settings.database_url,
            pool_size=settings.file_worker_database_pool_size,
            max_overflow=settings.file_worker_database_max_overflow,
        )
        context_protector = AesGcmUploadContextProtector.from_base64url_key(
            settings.file_upload_context_key.get_secret_value()
        )
        persistence = SqlAlchemyFilePersistence(database.session_factory)
        upload_handler = VerifyUploadCompletion(
            object_storage=object_storage,
            context_protector=context_protector,
            persistence=persistence,
            max_size_bytes=settings.file_upload_max_size_bytes,
        )
        malware_scan_handler = ApplyMalwareScanResult(
            object_storage=object_storage,
            persistence=persistence,
        )
        auto_lock_renewer = AutoLockRenewer(
            max_lock_renewal_duration=(settings.file_worker_max_lock_renewal_seconds)
        )
        worker = AzureServiceBusUploadCompletionWorker(
            client=client,
            queue_name=settings.azure_service_bus_queue_name,
            mapper=AzureBlobCreatedEventMapper(
                expected_source=settings.azure_event_grid_expected_source,
                expected_container=settings.azure_storage_container,
                nexus_source=settings.file_upload_completion_source,
            ),
            handler=upload_handler,
            auto_lock_renewer=auto_lock_renewer,
        )
        malware_scan_worker = AzureServiceBusUploadCompletionWorker(
            client=client,
            queue_name=settings.azure_service_bus_malware_scan_queue_name,
            mapper=AzureMalwareScanResultMapper(
                expected_topic=settings.azure_malware_scan_expected_topic,
                expected_storage_account=_storage_account_name(
                    str(settings.azure_storage_account_url)
                ),
                expected_container=settings.azure_storage_container,
                nexus_source=settings.file_malware_scan_source,
            ),
            handler=malware_scan_handler,
            auto_lock_renewer=auto_lock_renewer,
        )
    except (Exception, CancelledError) as construction_error:
        try:
            await _close_partial_resources(
                auto_lock_renewer,
                client,
                blob_service_client,
                database,
                credential,
            )
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001
            construction_error.add_note(
                "A File worker resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        raise

    return FileWorkerComposition(
        worker=worker,
        malware_scan_worker=malware_scan_worker,
        service_bus_client=client,
        blob_service_client=blob_service_client,
        database=database,
        credential=credential,
        auto_lock_renewer=auto_lock_renewer,
    )


async def _close_partial_resources(
    auto_lock_renewer: AutoLockRenewer | None,
    client: ServiceBusClient | None,
    blob_service_client: BlobServiceClient | None,
    database: Database | None,
    credential: ManagedIdentityCredential | None,
) -> None:
    try:
        if auto_lock_renewer is not None:
            await auto_lock_renewer.close()
    finally:
        try:
            if client is not None:
                await client.close()
        finally:
            try:
                if blob_service_client is not None:
                    await blob_service_client.close()
            finally:
                try:
                    if database is not None:
                        await database.dispose()
                finally:
                    if credential is not None:
                        await credential.close()


def _storage_account_name(account_url: str) -> str:
    host = urlsplit(account_url).hostname
    if host is None or "." not in host:
        raise ValueError("Azure storage account URL is invalid")
    account_name = host.split(".", 1)[0]
    if not account_name:
        raise ValueError("Azure storage account URL is invalid")
    return account_name


__all__ = [
    "FileWorkerComposition",
    "build_file_worker_composition",
]
