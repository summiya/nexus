from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from pydantic import ValidationError

from nexus.dev import local_file_worker
from nexus.dev.local_file_worker import (
    LocalFileWorkerSettings,
    build_local_file_worker_composition,
)

CONTEXT_KEY = "bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"


def _settings(**overrides: object) -> LocalFileWorkerSettings:
    values: dict[str, object] = {
        "app_env": "development",
        "database_url": "postgresql://nexus:nexus@postgres:5432/nexus",
        "file_upload_context_key": CONTEXT_KEY,
        "azure_storage_connection_string": "UseDevelopmentStorage=true",
        "azure_storage_container": "nexus-files",
        "azure_storage_account_name": "devstoreaccount1",
        "azure_service_bus_connection_string": (
            "Endpoint=sb://servicebus-emulator;"
            "SharedAccessKeyName=RootManageSharedAccessKey;"
            "SharedAccessKey=SAS_KEY_VALUE;"
            "UseDevelopmentEmulator=true;"
        ),
        "azure_service_bus_queue_name": "file-upload-completions",
        "azure_service_bus_malware_scan_queue_name": "file-malware-scan-results",
        "azure_event_grid_expected_source": "/local/azurite",
        "azure_malware_scan_expected_topic": "/local/defender",
        **overrides,
    }
    return LocalFileWorkerSettings(_env_file=None, **values)


def test_local_worker_accepts_development_emulator_configuration() -> None:
    settings = _settings()

    assert settings.app_env == "development"
    assert settings.azure_storage_account_name == "devstoreaccount1"
    assert settings.file_upload_completion_source == "local-azurite"
    assert settings.file_malware_scan_source == "local-malware-simulator"


@pytest.mark.parametrize(
    "environment", ["production", "staging", "local", "DEVELOPMENT"]
)
def test_local_worker_rejects_non_local_environments(environment: str) -> None:
    with pytest.raises(ValidationError, match="restricted to development and test"):
        _settings(app_env=environment)


@pytest.mark.parametrize(
    "field",
    [
        "azure_storage_container",
        "azure_storage_account_name",
        "azure_service_bus_queue_name",
        "azure_service_bus_malware_scan_queue_name",
        "azure_event_grid_expected_source",
        "azure_malware_scan_expected_topic",
    ],
)
def test_local_worker_rejects_blank_transport_identifiers(field: str) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: " "})


class FakeServiceBusClient:
    connection_strings: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self.close_calls = 0

    @classmethod
    def from_connection_string(cls, value: str) -> FakeServiceBusClient:
        cls.connection_strings.append(value)
        return cls()

    async def close(self) -> None:
        self.close_calls += 1


class FakeContainerClient:
    pass


class FakeBlobServiceClient:
    connection_strings: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self.close_calls = 0
        self.container_names: list[str] = []

    @classmethod
    def from_connection_string(cls, value: str) -> FakeBlobServiceClient:
        cls.connection_strings.append(value)
        return cls()

    def get_container_client(self, name: str) -> FakeContainerClient:
        self.container_names.append(name)
        return FakeContainerClient()

    async def close(self) -> None:
        self.close_calls += 1


class FakeDatabase:
    def __init__(self) -> None:
        self.session_factory = object()
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


class FakeAutoLockRenewer:
    instances: ClassVar[list[FakeAutoLockRenewer]] = []

    def __init__(self, *, max_lock_renewal_duration: int) -> None:
        self.max_lock_renewal_duration = max_lock_renewal_duration
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


def test_local_composition_uses_connection_string_clients_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        FakeServiceBusClient.connection_strings = []
        FakeBlobServiceClient.connection_strings = []
        FakeAutoLockRenewer.instances = []
        database = FakeDatabase()

        monkeypatch.setattr(
            local_file_worker,
            "ServiceBusClient",
            FakeServiceBusClient,
        )
        monkeypatch.setattr(
            local_file_worker,
            "BlobServiceClient",
            FakeBlobServiceClient,
        )
        monkeypatch.setattr(
            local_file_worker,
            "AutoLockRenewer",
            FakeAutoLockRenewer,
        )
        monkeypatch.setattr(
            local_file_worker,
            "build_database",
            lambda *args, **kwargs: database,
        )

        settings = _settings()
        composition = await build_local_file_worker_composition(settings)

        assert FakeServiceBusClient.connection_strings == [
            settings.azure_service_bus_connection_string.get_secret_value()
        ]
        assert FakeBlobServiceClient.connection_strings == [
            settings.azure_storage_connection_string.get_secret_value()
        ]
        assert composition.upload_worker.queue_name == "file-upload-completions"
        assert composition.malware_scan_worker.queue_name == (
            "file-malware-scan-results"
        )
        assert composition.blob_service_client.container_names == ["nexus-files"]

        await composition.close()
        assert composition.service_bus_client.close_calls == 1
        assert composition.blob_service_client.close_calls == 1
        assert database.dispose_calls == 1
        assert composition.auto_lock_renewer.close_calls == 1

    asyncio.run(scenario())
