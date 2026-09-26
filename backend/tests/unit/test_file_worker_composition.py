from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import ClassVar

import pytest

from nexus.composition import file_worker as composition_module
from nexus.composition.file_worker import (
    FileWorkerConfigurationError,
    build_file_worker_composition,
)
from nexus.config.file_worker_settings import FileWorkerSettings
from nexus.files.ports import UploadCompletionEvent


class StubHandler:
    async def handle(self, event: UploadCompletionEvent) -> None:
        del event


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


def _settings(**changes: object) -> FileWorkerSettings:
    return FileWorkerSettings(
        _env_file=None,
        azure_service_bus_fully_qualified_namespace=(
            "nexus.servicebus.windows.net"
        ),
        azure_service_bus_queue_name="file-upload-completions",
        azure_event_grid_expected_source="/subscriptions/source",
        azure_storage_container="nexus-files",
        **changes,
    )


def test_builds_dedicated_worker_and_closes_owned_resources_once() -> None:
    async def scenario() -> None:
        composition = await build_file_worker_composition(
            _settings(),
            handler=StubHandler(),
        )

        credential = FakeCredential.instances[0]
        client = FakeServiceBusClient.instances[0]
        renewer = FakeAutoLockRenewer.instances[0]
        assert credential.client_id is None
        assert client.namespace == "nexus.servicebus.windows.net"
        assert client.credential is credential
        assert renewer.duration == 300
        assert composition.worker.queue_name == "file-upload-completions"
        assert composition.worker.auto_lock_renewer is renewer

        await composition.close()

        assert renewer.close_calls == 1
        assert client.close_calls == 1
        assert credential.close_calls == 1

    asyncio.run(scenario())


def test_uses_user_assigned_managed_identity_client_id() -> None:
    async def scenario() -> None:
        client_id = "11111111-1111-4111-8111-111111111111"
        composition = await build_file_worker_composition(
            _settings(
                azure_service_bus_managed_identity_client_id=client_id,
            ),
            handler=StubHandler(),
        )

        assert FakeCredential.instances[0].client_id == client_id
        await composition.close()

    asyncio.run(scenario())


def test_missing_handler_fails_before_constructing_azure_resources() -> None:
    async def scenario() -> None:
        with pytest.raises(
            FileWorkerConfigurationError,
            match="File upload completion handler is not configured",
        ):
            await build_file_worker_composition(_settings(), handler=None)

        assert FakeCredential.instances == []
        assert FakeServiceBusClient.instances == []
        assert FakeAutoLockRenewer.instances == []

    asyncio.run(scenario())


def test_partial_construction_closes_credential() -> None:
    async def scenario() -> None:
        FakeServiceBusClient.construction_error = RuntimeError("construction failed")

        with pytest.raises(RuntimeError, match="construction failed"):
            await build_file_worker_composition(
                _settings(),
                handler=StubHandler(),
            )

        assert FakeCredential.instances[0].close_calls == 1

    asyncio.run(scenario())


def test_composition_imports_no_web_llm_mail_redis_or_database_modules() -> None:
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
                "nexus.infrastructure.persistence",
                "nexus.llm",
                "redis",
                "sqlalchemy",
            )
        )
        for module in imports
    )
