from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import ClassVar
from uuid import UUID

import pytest

from nexus.composition import storage as storage_composition
from nexus.composition.storage import (
    StorageConfigurationError,
    build_storage_composition,
)
from nexus.config.settings import Settings
from nexus.infrastructure.storage import AzureBlobObjectStorage


class StubObjectStorage:
    async def create_object(
        self,
        *,
        storage_key: str,
        content: AsyncIterable[bytes],
    ) -> None:
        del storage_key, content

    def stream_object(self, *, storage_key: str) -> AsyncIterator[bytes]:
        del storage_key
        return self._empty_stream()

    async def delete_object(self, *, storage_key: str) -> None:
        del storage_key

    async def _empty_stream(self) -> AsyncIterator[bytes]:
        if False:
            yield b""


class FakeManagedIdentityCredential:
    instances: ClassVar[list[FakeManagedIdentityCredential]] = []

    def __init__(self, *, client_id: str | None = None) -> None:
        self.client_id = client_id
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


class FakeBlobServiceClient:
    instances: ClassVar[list[FakeBlobServiceClient]] = []
    connection_strings: ClassVar[list[str]] = []
    construction_error: ClassVar[BaseException | None] = None
    container_error: ClassVar[BaseException | None] = None

    def __init__(
        self,
        account_url: str,
        credential: object | None = None,
        *,
        connection_string: str | None = None,
    ) -> None:
        if self.__class__.construction_error is not None:
            raise self.__class__.construction_error
        self.account_url = account_url
        self.credential = credential
        self.connection_string = connection_string
        self.container_names: list[str] = []
        self.container_client = object()
        self.close_calls = 0
        self.close_error: BaseException | None = None
        self.__class__.instances.append(self)

    @classmethod
    def from_connection_string(cls, connection_string: str) -> FakeBlobServiceClient:
        cls.connection_strings.append(connection_string)
        return cls(
            "http://azurite.local",
            connection_string=connection_string,
        )

    def get_container_client(self, container_name: str) -> object:
        self.container_names.append(container_name)
        if self.__class__.container_error is not None:
            raise self.__class__.container_error
        return self.container_client

    async def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


@pytest.fixture(autouse=True)
def fake_azure_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeManagedIdentityCredential.instances = []
    FakeBlobServiceClient.instances = []
    FakeBlobServiceClient.connection_strings = []
    FakeBlobServiceClient.construction_error = None
    FakeBlobServiceClient.container_error = None
    monkeypatch.setattr(
        storage_composition,
        "ManagedIdentityCredential",
        FakeManagedIdentityCredential,
    )
    monkeypatch.setattr(
        storage_composition,
        "BlobServiceClient",
        FakeBlobServiceClient,
    )


def build_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ["https://nexus.example"],
        "otp_hmac_secret": "test-secret-value-with-enough-length",
        "auth_token_secret": "test-auth-token-secret-with-enough-length",
        "refresh_token_secret": "test-refresh-token-secret-with-enough-length",
        "storage_provider": "azure_blob",
        "azure_storage_container": "nexus-files",
        "azure_storage_connection_string": None,
        "azure_storage_account_url": None,
        "azure_storage_managed_identity_client_id": None,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_injected_storage_bypasses_azure_configuration_and_construction() -> None:
    async def scenario() -> None:
        injected = StubObjectStorage()

        composition = await build_storage_composition(
            build_settings(storage_provider="unsupported"),
            object_storage=injected,
        )
        await composition.close()

        assert composition.object_storage is injected
        assert FakeBlobServiceClient.instances == []
        assert FakeManagedIdentityCredential.instances == []

    asyncio.run(scenario())


def test_development_connection_string_builds_azurite_storage() -> None:
    async def scenario() -> None:
        settings = build_settings(
            app_env="development",
            azure_storage_connection_string="UseDevelopmentStorage=true",
        )

        composition = await build_storage_composition(settings)
        service_client = FakeBlobServiceClient.instances[0]

        assert isinstance(composition.object_storage, AzureBlobObjectStorage)
        assert FakeBlobServiceClient.connection_strings == [
            "UseDevelopmentStorage=true"
        ]
        assert service_client.container_names == ["nexus-files"]
        assert composition.object_storage._container_client is (
            service_client.container_client
        )
        assert FakeManagedIdentityCredential.instances == []

        await composition.close()
        assert service_client.close_calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("app_env", ["production", "staging", "local", "DEVELOPMENT"])
def test_connection_string_is_rejected_outside_explicit_local_test_environments(
    app_env: str,
) -> None:
    async def scenario() -> None:
        with pytest.raises(
            StorageConfigurationError,
            match="restricted to development and test environments",
        ):
            await build_storage_composition(
                build_settings(
                    app_env=app_env,
                    azure_storage_connection_string="secret-value",
                )
            )

        assert FakeBlobServiceClient.instances == []

    asyncio.run(scenario())


def test_test_environment_allows_connection_string() -> None:
    async def scenario() -> None:
        composition = await build_storage_composition(
            build_settings(
                app_env="test",
                azure_storage_connection_string="UseDevelopmentStorage=true",
            )
        )

        assert FakeBlobServiceClient.connection_strings == [
            "UseDevelopmentStorage=true"
        ]
        await composition.close()

    asyncio.run(scenario())


def test_account_url_uses_system_assigned_managed_identity() -> None:
    async def scenario() -> None:
        composition = await build_storage_composition(
            build_settings(
                app_env="production",
                azure_storage_account_url="https://account.blob.core.windows.net",
            )
        )
        credential = FakeManagedIdentityCredential.instances[0]
        service_client = FakeBlobServiceClient.instances[0]

        assert credential.client_id is None
        assert service_client.account_url == ("https://account.blob.core.windows.net/")
        assert service_client.credential is credential

        await composition.close()
        assert service_client.close_calls == 1
        assert credential.close_calls == 1

    asyncio.run(scenario())


def test_account_url_uses_configured_user_assigned_identity() -> None:
    async def scenario() -> None:
        client_id = UUID("00000000-0000-0000-0000-000000000123")
        composition = await build_storage_composition(
            build_settings(
                app_env="unexpected-environment",
                azure_storage_account_url="https://account.blob.core.windows.net",
                azure_storage_managed_identity_client_id=client_id,
            )
        )

        assert FakeManagedIdentityCredential.instances[0].client_id == str(client_id)
        await composition.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"storage_provider": "unsupported"}, "Unsupported storage provider"),
        ({"azure_storage_container": "  "}, "container is not configured"),
        ({}, "authentication is not configured"),
        (
            {"azure_storage_connection_string": "  "},
            "connection string must not be blank",
        ),
        (
            {
                "azure_storage_connection_string": "connection-string",
                "azure_storage_account_url": "https://account.blob.core.windows.net",
            },
            "exactly one",
        ),
        (
            {
                "azure_storage_connection_string": "connection-string",
                "azure_storage_managed_identity_client_id": (
                    "00000000-0000-0000-0000-000000000123"
                ),
            },
            "client ID requires",
        ),
        (
            {"azure_storage_account_url": "http://account.blob.core.windows.net"},
            "must use HTTPS",
        ),
    ],
)
def test_invalid_storage_configuration_fails_before_client_construction(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    async def scenario() -> None:
        with pytest.raises(StorageConfigurationError, match=expected_message):
            await build_storage_composition(build_settings(**overrides))

        assert FakeBlobServiceClient.instances == []
        assert FakeManagedIdentityCredential.instances == []

    asyncio.run(scenario())


def test_service_client_failure_closes_already_created_credential() -> None:
    async def scenario() -> None:
        construction_error = RuntimeError("service client failed")
        FakeBlobServiceClient.construction_error = construction_error

        with pytest.raises(RuntimeError) as captured:
            await build_storage_composition(
                build_settings(
                    app_env="production",
                    azure_storage_account_url=("https://account.blob.core.windows.net"),
                )
            )

        assert captured.value is construction_error
        assert FakeManagedIdentityCredential.instances[0].close_calls == 1

    asyncio.run(scenario())


def test_container_derivation_failure_closes_service_client_and_credential() -> None:
    async def scenario() -> None:
        container_error = RuntimeError("container derivation failed")
        FakeBlobServiceClient.container_error = container_error

        with pytest.raises(RuntimeError) as captured:
            await build_storage_composition(
                build_settings(
                    app_env="production",
                    azure_storage_account_url=("https://account.blob.core.windows.net"),
                )
            )

        service_client = FakeBlobServiceClient.instances[0]
        credential = FakeManagedIdentityCredential.instances[0]
        assert captured.value is container_error
        assert service_client.close_calls == 1
        assert credential.close_calls == 1

    asyncio.run(scenario())


def test_connection_string_container_failure_closes_service_client() -> None:
    async def scenario() -> None:
        container_error = RuntimeError("container derivation failed")
        FakeBlobServiceClient.container_error = container_error

        with pytest.raises(RuntimeError) as captured:
            await build_storage_composition(
                build_settings(
                    app_env="development",
                    azure_storage_connection_string="UseDevelopmentStorage=true",
                )
            )

        service_client = FakeBlobServiceClient.instances[0]
        assert captured.value is container_error
        assert service_client.close_calls == 1
        assert FakeManagedIdentityCredential.instances == []

    asyncio.run(scenario())


def test_service_close_failure_still_closes_owned_credential() -> None:
    async def scenario() -> None:
        composition = await build_storage_composition(
            build_settings(
                app_env="production",
                azure_storage_account_url="https://account.blob.core.windows.net",
            )
        )
        service_client = FakeBlobServiceClient.instances[0]
        credential = FakeManagedIdentityCredential.instances[0]
        service_client.close_error = RuntimeError("close failed")

        with pytest.raises(RuntimeError, match="close failed"):
            await composition.close()

        assert service_client.close_calls == 1
        assert credential.close_calls == 1

    asyncio.run(scenario())


def test_composition_exposes_only_port_and_private_cleanup_callback() -> None:
    async def scenario() -> None:
        composition = await build_storage_composition(
            build_settings(
                azure_storage_connection_string="UseDevelopmentStorage=true",
            )
        )

        assert isinstance(composition.object_storage, AzureBlobObjectStorage)
        assert set(vars(composition)) == {"object_storage", "_close_callback"}
        await composition.close()

    asyncio.run(scenario())
