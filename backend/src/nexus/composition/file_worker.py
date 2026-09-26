"""Composition and lifecycle for the dedicated File completion worker."""

from __future__ import annotations

from asyncio import CancelledError
from dataclasses import dataclass

from azure.identity.aio import ManagedIdentityCredential
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient

from nexus.config.file_worker_settings import FileWorkerSettings
from nexus.files.ports import UploadCompletionHandler
from nexus.infrastructure.messaging import AzureServiceBusUploadCompletionWorker
from nexus.infrastructure.storage import AzureBlobCreatedEventMapper


class FileWorkerConfigurationError(ValueError):
    """The File completion worker cannot start safely."""


@dataclass(frozen=True)
class FileWorkerComposition:
    """Own the dedicated worker and its Azure resources."""

    worker: AzureServiceBusUploadCompletionWorker
    service_bus_client: ServiceBusClient
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
                await self.credential.close()


async def build_file_worker_composition(
    settings: FileWorkerSettings,
    *,
    handler: UploadCompletionHandler | None,
) -> FileWorkerComposition:
    """Build the worker without constructing FastAPI or database resources."""

    if handler is None:
        raise FileWorkerConfigurationError(
            "File upload completion handler is not configured."
        )

    credential: ManagedIdentityCredential | None = None
    client: ServiceBusClient | None = None
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
        auto_lock_renewer = AutoLockRenewer(
            max_lock_renewal_duration=(
                settings.file_worker_max_lock_renewal_seconds
            )
        )
        worker = AzureServiceBusUploadCompletionWorker(
            client=client,
            queue_name=settings.azure_service_bus_queue_name,
            mapper=AzureBlobCreatedEventMapper(
                expected_source=settings.azure_event_grid_expected_source,
                expected_container=settings.azure_storage_container,
                nexus_source=settings.file_upload_completion_source,
            ),
            handler=handler,
            auto_lock_renewer=auto_lock_renewer,
        )
    except (Exception, CancelledError) as construction_error:
        try:
            await _close_partial_resources(
                auto_lock_renewer,
                client,
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
        service_bus_client=client,
        credential=credential,
        auto_lock_renewer=auto_lock_renewer,
    )


async def _close_partial_resources(
    auto_lock_renewer: AutoLockRenewer | None,
    client: ServiceBusClient | None,
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
            if credential is not None:
                await credential.close()


__all__ = [
    "FileWorkerComposition",
    "FileWorkerConfigurationError",
    "build_file_worker_composition",
]
