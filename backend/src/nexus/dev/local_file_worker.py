"""Development-only File worker for Azurite and the Service Bus emulator."""

from __future__ import annotations

import asyncio
import signal
from asyncio import CancelledError
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient
from azure.storage.blob.aio import BlobServiceClient
from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.config.settings import (
    DEFAULT_FILE_UPLOAD_MAX_SIZE_BYTES,
    ROOT_ENV_FILE,
    validate_file_upload_context_key,
)
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
from nexus.logging import configure_logging, get_logger

_LOCAL_ENVIRONMENTS = frozenset({"development", "test"})

logger = get_logger(__name__)


class LocalFileWorkerSettings(BaseSettings):
    """Configuration accepted only by the local Azure-emulator worker."""

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = Field(min_length=1)
    file_upload_max_size_bytes: int = Field(
        default=DEFAULT_FILE_UPLOAD_MAX_SIZE_BYTES,
        gt=0,
    )
    file_upload_context_key: SecretStr
    file_worker_database_pool_size: int = Field(default=2, ge=1, le=20)
    file_worker_database_max_overflow: int = Field(default=0, ge=0, le=20)
    file_worker_max_lock_renewal_seconds: int = Field(default=300, ge=60, le=600)

    azure_storage_connection_string: SecretStr
    azure_storage_container: str = Field(min_length=1, max_length=63)
    azure_storage_account_name: str = Field(
        default="devstoreaccount1",
        min_length=1,
        max_length=255,
    )

    azure_service_bus_connection_string: SecretStr
    azure_service_bus_queue_name: str = Field(min_length=1, max_length=260)
    azure_service_bus_malware_scan_queue_name: str = Field(
        default="file-malware-scan-results",
        min_length=1,
        max_length=260,
    )

    azure_event_grid_expected_source: str = Field(min_length=1, max_length=1024)
    azure_malware_scan_expected_topic: str = Field(min_length=1, max_length=2048)
    file_upload_completion_source: str = Field(
        default="local-azurite",
        min_length=1,
        max_length=1024,
    )
    file_malware_scan_source: str = Field(
        default="local-malware-simulator",
        min_length=1,
        max_length=1024,
    )

    @field_validator(
        "azure_storage_container",
        "azure_storage_account_name",
        "azure_service_bus_queue_name",
        "azure_service_bus_malware_scan_queue_name",
        "azure_event_grid_expected_source",
        "azure_malware_scan_expected_topic",
        "file_upload_completion_source",
        "file_malware_scan_source",
    )
    @classmethod
    def reject_blank_or_padded_text(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Local File worker configuration is invalid")
        return value

    @field_validator(
        "azure_storage_connection_string",
        "azure_service_bus_connection_string",
    )
    @classmethod
    def require_nonblank_connection_string(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Local File worker connection string must not be blank")
        return value

    @field_validator("file_upload_context_key")
    @classmethod
    def validate_upload_context_key(
        cls,
        value: SecretStr,
        info: ValidationInfo,
    ) -> SecretStr:
        return validate_file_upload_context_key(
            value,
            app_env=info.data.get("app_env"),
        )

    @field_validator("app_env")
    @classmethod
    def require_local_environment(cls, value: str) -> str:
        if value not in _LOCAL_ENVIRONMENTS:
            raise ValueError(
                "Local File worker is restricted to development and test environments"
            )
        return value

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


@dataclass(frozen=True)
class LocalFileWorkerComposition:
    """Own the local worker resources."""

    upload_worker: AzureServiceBusUploadCompletionWorker
    malware_scan_worker: AzureServiceBusUploadCompletionWorker
    service_bus_client: ServiceBusClient
    blob_service_client: BlobServiceClient
    database: Database
    auto_lock_renewer: AutoLockRenewer

    async def close(self) -> None:
        try:
            await self.auto_lock_renewer.close()
        finally:
            try:
                await self.service_bus_client.close()
            finally:
                try:
                    await self.blob_service_client.close()
                finally:
                    await self.database.dispose()


def load_local_file_worker_settings(
    *,
    env_file: Path | None = ROOT_ENV_FILE,
) -> LocalFileWorkerSettings:
    """Load the local worker without enabling local auth in production settings."""

    return LocalFileWorkerSettings(_env_file=env_file)  # type: ignore[call-arg]


async def build_local_file_worker_composition(
    settings: LocalFileWorkerSettings,
) -> LocalFileWorkerComposition:
    """Compose emulator clients around the same production File handlers."""

    service_bus_client: ServiceBusClient | None = None
    blob_service_client: BlobServiceClient | None = None
    database: Database | None = None
    auto_lock_renewer: AutoLockRenewer | None = None
    try:
        service_bus_client = ServiceBusClient.from_connection_string(
            settings.azure_service_bus_connection_string.get_secret_value()
        )
        blob_service_client = BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string.get_secret_value()
        )
        object_storage = AzureBlobObjectStorage(
            blob_service_client.get_container_client(settings.azure_storage_container)
        )
        database = build_database(
            settings.database_url,
            pool_size=settings.file_worker_database_pool_size,
            max_overflow=settings.file_worker_database_max_overflow,
        )
        persistence = SqlAlchemyFilePersistence(database.session_factory)
        context_protector = AesGcmUploadContextProtector.from_base64url_key(
            settings.file_upload_context_key.get_secret_value()
        )
        upload_handler = VerifyUploadCompletion(
            object_storage=object_storage,
            context_protector=context_protector,
            persistence=persistence,
            max_size_bytes=settings.file_upload_max_size_bytes,
        )
        malware_handler = ApplyMalwareScanResult(
            object_storage=object_storage,
            persistence=persistence,
        )
        auto_lock_renewer = AutoLockRenewer(
            max_lock_renewal_duration=settings.file_worker_max_lock_renewal_seconds
        )
        upload_worker = AzureServiceBusUploadCompletionWorker(
            client=service_bus_client,
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
            client=service_bus_client,
            queue_name=settings.azure_service_bus_malware_scan_queue_name,
            mapper=AzureMalwareScanResultMapper(
                expected_topic=settings.azure_malware_scan_expected_topic,
                expected_storage_account=settings.azure_storage_account_name,
                expected_container=settings.azure_storage_container,
                nexus_source=settings.file_malware_scan_source,
            ),
            handler=malware_handler,
            auto_lock_renewer=auto_lock_renewer,
        )
    except (Exception, CancelledError) as construction_error:
        try:
            await _close_partial_resources(
                auto_lock_renewer,
                service_bus_client,
                blob_service_client,
                database,
            )
        except (Exception, CancelledError) as cleanup_error:  # noqa: BLE001
            construction_error.add_note(
                "A local File worker resource also failed during startup cleanup: "
                f"{type(cleanup_error).__name__}"
            )
        raise

    return LocalFileWorkerComposition(
        upload_worker=upload_worker,
        malware_scan_worker=malware_scan_worker,
        service_bus_client=service_bus_client,
        blob_service_client=blob_service_client,
        database=database,
        auto_lock_renewer=auto_lock_renewer,
    )


async def run_local_file_worker(settings: LocalFileWorkerSettings) -> None:
    """Run the emulator-backed workers until shutdown."""

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    installed_signals: list[signal.Signals] = []
    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(handled_signal, stop_event.set)
        except NotImplementedError:  # pragma: no cover
            continue
        installed_signals.append(handled_signal)

    composition: LocalFileWorkerComposition | None = None
    try:
        composition = await build_local_file_worker_composition(settings)
        async with asyncio.TaskGroup() as workers:
            workers.create_task(composition.upload_worker.run(stop_event))
            workers.create_task(composition.malware_scan_worker.run(stop_event))
    finally:
        for handled_signal in installed_signals:
            loop.remove_signal_handler(handled_signal)
        if composition is not None:
            await _settle_cleanup(composition.close())


async def _close_partial_resources(
    auto_lock_renewer: AutoLockRenewer | None,
    service_bus_client: ServiceBusClient | None,
    blob_service_client: BlobServiceClient | None,
    database: Database | None,
) -> None:
    try:
        if auto_lock_renewer is not None:
            await auto_lock_renewer.close()
    finally:
        try:
            if service_bus_client is not None:
                await service_bus_client.close()
        finally:
            try:
                if blob_service_client is not None:
                    await blob_service_client.close()
            finally:
                if database is not None:
                    await database.dispose()


async def _settle_cleanup(operation: Coroutine[Any, Any, None]) -> None:
    cleanup = asyncio.create_task(operation)
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        raise


def main() -> None:
    configure_logging()
    try:
        settings = load_local_file_worker_settings()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "local_file_worker_startup_failed",
            error_type=type(exc).__name__,
        )
        raise SystemExit(1) from None

    configure_logging(settings.log_level)
    try:
        asyncio.run(run_local_file_worker(settings))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "local_file_worker_runtime_failed",
            error_type=type(exc).__name__,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
