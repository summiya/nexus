from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import ClassVar, cast
from unittest.mock import Mock

import pytest

from nexus.composition import file_worker as composition_module
from nexus.composition.file_worker import build_file_worker_composition
from nexus.config.file_worker_settings import FileWorkerSettings
from nexus.files.application import VerifyUploadCompletion
from nexus.infrastructure.persistence.session import Database

DEVELOPMENT_CONTEXT_KEY = "bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"


class FakeCredential:
    instances: ClassVar[list[FakeCredential]] = []

    def __init__(self, *, client_id: str | None = None) -> None:
        self.client_id = client_id
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


class FakeServiceBusClient:
    instances: ClassVar[list[FakeServiceBusClient]] = []
    construction_error: BaseException | None = None

    def __init__(
        self,
        *,
        fully_qualified_namespace: str,
        credential: object,
    ) -> None:
        if self.__class__.construction_error is not None:
            raise self.__class__.construction_error
        self.namespace = fully_qualified_namespace
        self.credential = credential
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


class FakeBlobServiceClient:
    instances: ClassVar[list[FakeBlobServiceClient]] = []
    construction_error: BaseException | None = None

    def __init__(self, *, account_url: str, credential: object) -> None:
        if self.__class__.construction_error is not None:
            raise self.__class__.construction_error
        self.account_url = account_url
        self.credential = credential
        self.container_names: list[str] = []
        self.close_calls = 0
        self.__class__.instances.append(self)

    def get_container_client(self, container_name: str) -> object:
        self.container_names.append(container_name)
        return object()

    async def close(self) -> None:
        self.close_calls += 1


class FakeDatabase:
    instances: ClassVar[list[FakeDatabase]] = []

    def __init__(
        self,
        *,
        database_url: str,
        pool_size: int,
        max_overflow: int,
    ) -> None:
        self.session_factory = Mock()
        self.database_url = database_url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.dispose_calls = 0
        self.__class__.instances.append(self)

    async def dispose(self) -> None:
        self.dispose_calls += 1


class FakeAutoLockRenewer:
    instances: ClassVar[list[FakeAutoLockRenewer]] = []
    construction_error: BaseException | None = None

    def __init__(self, *, max_lock_renewal_duration: float) -> None:
        if self.__class__.construction_error is not None:
            raise self.__class__.construction_error
        self.duration = max_lock_renewal_duration
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


@pytest.fixture(autouse=True)
def fake_azure_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCredential.instances = []
    FakeServiceBusClient.instances = []
    FakeServiceBusClient.construction_error = None
    FakeBlobServiceClient.instances = []
    FakeBlobServiceClient.construction_error = None
    FakeDatabase.instances = []
    FakeAutoLockRenewer.instances = []
    FakeAutoLockRenewer.construction_error = None
    monkeypatch.setattr(
        composition_module,
        "ManagedIdentityCredential",
        FakeCredential,
    )
    monkeypatch.setattr(
        composition_module,
        "ServiceBusClient",
        FakeServiceBusClient,
    )
    monkeypatch.setattr(
        composition_module,
        "AutoLockRenewer",
        FakeAutoLockRenewer,
    )
    monkeypatch.setattr(
        composition_module,
        "BlobServiceClient",
        FakeBlobServiceClient,
    )

    def build_database(
        database_url: str,
        *,
        pool_size: int,
        max_overflow: int,
    ) -> Database:
        database = FakeDatabase(
            database_url=database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        return cast(Database, database)

    monkeypatch.setattr(composition_module, "build_database", build_database)


def _settings(**changes: object) -> FileWorkerSettings:
    return FileWorkerSettings(
        _env_file=None,
        database_url="postgresql://nexus:nexus@postgres:5432/nexus",
        file_upload_context_key=DEVELOPMENT_CONTEXT_KEY,
        azure_service_bus_fully_qualified_namespace=("nexus.servicebus.windows.net"),
        azure_service_bus_queue_name="file-upload-completions",
        azure_event_grid_expected_source="/subscriptions/source",
        azure_storage_container="nexus-files",
        azure_storage_account_url="https://nexus.blob.core.windows.net",
        **changes,
    )


def test_builds_dedicated_worker_and_closes_owned_resources_once() -> None:
    async def scenario() -> None:
        composition = await build_file_worker_composition(_settings())

        credential = FakeCredential.instances[0]
        client = FakeServiceBusClient.instances[0]
        renewer = FakeAutoLockRenewer.instances[0]
        blob_client = FakeBlobServiceClient.instances[0]
        database = FakeDatabase.instances[0]
        assert credential.client_id is None
        assert client.namespace == "nexus.servicebus.windows.net"
        assert client.credential is credential
        assert blob_client.credential is credential
        assert blob_client.account_url == "https://nexus.blob.core.windows.net/"
        assert blob_client.container_names == ["nexus-files"]
        assert database.database_url == "postgresql://nexus:nexus@postgres:5432/nexus"
        assert database.pool_size == 2
        assert database.max_overflow == 0
        assert renewer.duration == 300
        assert composition.worker.queue_name == "file-upload-completions"
        assert composition.worker.auto_lock_renewer is renewer
        assert isinstance(composition.worker.handler, VerifyUploadCompletion)

        await composition.close()

        assert renewer.close_calls == 1
        assert client.close_calls == 1
        assert blob_client.close_calls == 1
        assert database.dispose_calls == 1
        assert credential.close_calls == 1

    asyncio.run(scenario())


def test_uses_user_assigned_managed_identity_client_id() -> None:
    async def scenario() -> None:
        client_id = "11111111-1111-4111-8111-111111111111"
        composition = await build_file_worker_composition(
            _settings(
                azure_service_bus_managed_identity_client_id=client_id,
            )
        )

        assert FakeCredential.instances[0].client_id == client_id
        await composition.close()

    asyncio.run(scenario())


def test_partial_construction_closes_credential() -> None:
    async def scenario() -> None:
        FakeServiceBusClient.construction_error = RuntimeError("construction failed")

        with pytest.raises(RuntimeError, match="construction failed"):
            await build_file_worker_composition(_settings())

        assert FakeCredential.instances[0].close_calls == 1

    asyncio.run(scenario())


def test_late_construction_failure_closes_all_owned_resources() -> None:
    async def scenario() -> None:
        FakeAutoLockRenewer.construction_error = RuntimeError("construction failed")

        with pytest.raises(RuntimeError, match="construction failed"):
            await build_file_worker_composition(_settings())

        assert FakeServiceBusClient.instances[0].close_calls == 1
        assert FakeBlobServiceClient.instances[0].close_calls == 1
        assert FakeDatabase.instances[0].dispose_calls == 1
        assert FakeCredential.instances[0].close_calls == 1

    asyncio.run(scenario())


def test_composition_imports_no_unrelated_application_capabilities() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "nexus"
        / "composition"
        / "file_worker.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.startswith(
            (
                "fastapi",
                "nexus.authentication",
                "nexus.infrastructure.mailer",
                "nexus.llm",
                "redis",
                "sqlalchemy",
            )
        )
        for module in imports
    )
