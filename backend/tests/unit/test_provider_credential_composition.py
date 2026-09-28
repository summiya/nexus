from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from nexus.composition import provider_credentials as credential_composition
from nexus.composition.provider_credentials import (
    CredentialStoreConfigurationError,
    build_provider_credential_composition,
)
from nexus.config.settings import Settings
from nexus.infrastructure.credentials import (
    AzureKeyVaultCredentialStore,
    LocalEncryptedCredentialStore,
)
from nexus.model_providers.ports import CredentialStore

FILE_UPLOAD_CONTEXT_KEY = "ZW52LWZpbGUtdXBsb2FkLWNvbnRleHQta2V5LTAwMDE"


class FakeManagedIdentityCredential:
    instances: ClassVar[list[FakeManagedIdentityCredential]] = []

    def __init__(self, *, client_id: str | None = None) -> None:
        self.client_id = client_id
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


class FakeSecretClient:
    instances: ClassVar[list[FakeSecretClient]] = []
    construction_error: Exception | None = None

    def __init__(self, *, vault_url: str, credential: object) -> None:
        if self.__class__.construction_error is not None:
            raise self.__class__.construction_error
        self.vault_url = vault_url
        self.credential = credential
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self) -> None:
        self.close_calls += 1


def build_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key=FILE_UPLOAD_CONTEXT_KEY,
        **overrides,
    )


@pytest.fixture(autouse=True)
def fake_azure_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeManagedIdentityCredential.instances = []
    FakeSecretClient.instances = []
    FakeSecretClient.construction_error = None
    monkeypatch.setattr(
        credential_composition,
        "ManagedIdentityCredential",
        FakeManagedIdentityCredential,
    )
    monkeypatch.setattr(
        credential_composition,
        "SecretClient",
        FakeSecretClient,
    )


def test_unconfigured_store_is_optional() -> None:
    async def scenario() -> None:
        composition = await build_provider_credential_composition(build_settings())
        assert composition.store is None
        await composition.close()
        assert FakeManagedIdentityCredential.instances == []

    asyncio.run(scenario())


def test_explicit_store_injection_is_preserved_without_owned_cleanup() -> None:
    async def scenario() -> None:
        injected = Mock(spec=CredentialStore)
        composition = await build_provider_credential_composition(
            build_settings(),
            credential_store=injected,
        )
        assert composition.store is injected
        await composition.close()

    asyncio.run(scenario())


def test_local_store_requires_explicit_local_environment(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode("ascii")

    async def scenario() -> None:
        local = await build_provider_credential_composition(
            build_settings(
                app_env="development",
                credential_store_provider="local_encrypted",
                local_credential_store_path=tmp_path,
                local_credential_store_key=key,
            )
        )
        assert isinstance(local.store, LocalEncryptedCredentialStore)

        for environment in ("production", "staging", "unexpected"):
            with pytest.raises(
                CredentialStoreConfigurationError,
                match="restricted to development and test",
            ):
                await build_provider_credential_composition(
                    build_settings(
                        app_env=environment,
                        credential_store_provider="local_encrypted",
                        local_credential_store_path=tmp_path,
                        local_credential_store_key=key,
                    )
                )

    asyncio.run(scenario())


def test_azure_store_uses_managed_identity_and_owns_cleanup() -> None:
    async def scenario() -> None:
        client_id = uuid4()
        composition = await build_provider_credential_composition(
            build_settings(
                app_env="production",
                credential_store_provider="azure_key_vault",
                azure_key_vault_url="https://credentials.vault.azure.net",
                azure_key_vault_managed_identity_client_id=client_id,
            )
        )
        assert isinstance(composition.store, AzureKeyVaultCredentialStore)
        credential = FakeManagedIdentityCredential.instances[0]
        client = FakeSecretClient.instances[0]
        assert credential.client_id == str(client_id)
        assert client.vault_url == "https://credentials.vault.azure.net/"

        await composition.close()
        assert client.close_calls == 1
        assert credential.close_calls == 1

    asyncio.run(scenario())


def test_azure_construction_failure_closes_owned_credential() -> None:
    async def scenario() -> None:
        FakeSecretClient.construction_error = RuntimeError("construction failure")
        with pytest.raises(RuntimeError, match="construction failure"):
            await build_provider_credential_composition(
                build_settings(
                    credential_store_provider="azure_key_vault",
                    azure_key_vault_url="https://credentials.vault.azure.net",
                )
            )
        assert FakeManagedIdentityCredential.instances[0].close_calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "vault_url",
    [
        "http://credentials.vault.azure.net",
        "https://user:password@credentials.vault.azure.net",
        "https://credentials.vault.azure.net/path",
        "https://credentials.vault.azure.net?sig=value",
        "https://credentials.vault.azure.net#fragment",
    ],
)
def test_azure_vault_url_must_be_credential_free_https_root(vault_url: str) -> None:
    async def scenario() -> None:
        with pytest.raises(CredentialStoreConfigurationError):
            await build_provider_credential_composition(
                build_settings(
                    credential_store_provider="azure_key_vault",
                    azure_key_vault_url=vault_url,
                )
            )
        assert FakeManagedIdentityCredential.instances == []
        assert FakeSecretClient.instances == []

    asyncio.run(scenario())


def test_unsupported_explicit_provider_fails_closed() -> None:
    async def scenario() -> None:
        with pytest.raises(
            CredentialStoreConfigurationError,
            match="Unsupported credential store provider",
        ):
            await build_provider_credential_composition(
                build_settings(credential_store_provider="unknown")
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["local_encrypted", "azure_key_vault"])
def test_explicit_provider_rejects_mixed_provider_configuration(
    provider: str,
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        values: dict[str, object] = {
            "credential_store_provider": provider,
            "local_credential_store_path": tmp_path,
            "local_credential_store_key": Fernet.generate_key().decode("ascii"),
            "azure_key_vault_url": "https://credentials.vault.azure.net",
        }
        with pytest.raises(
            CredentialStoreConfigurationError,
            match="mixes provider settings",
        ):
            await build_provider_credential_composition(build_settings(**values))

    asyncio.run(scenario())
