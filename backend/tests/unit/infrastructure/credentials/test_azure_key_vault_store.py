from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.keyvault.secrets.aio import SecretClient

from nexus.infrastructure.credentials import AzureKeyVaultCredentialStore
from nexus.model_providers.domain import (
    CredentialReference,
    OrganizationProviderId,
    ProviderCredentialSecret,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStoreConflictError,
    CredentialStoreError,
)


class FakeSecretClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.set_error: Exception | None = None
        self.get_error: Exception | None = None
        self.delete_error: Exception | None = None

    async def set_secret(self, name: str, value: str) -> object:
        if self.set_error is not None:
            raise self.set_error
        self.set_calls.append((name, value))
        self.values[name] = value
        return object()

    async def get_secret(self, name: str) -> object:
        if self.get_error is not None:
            raise self.get_error
        self.get_calls.append(name)
        return SimpleNamespace(value=self.values[name])

    async def delete_secret(self, name: str) -> object:
        if self.delete_error is not None:
            raise self.delete_error
        self.delete_calls.append(name)
        self.values.pop(name, None)
        return object()


def _scope() -> tuple[UUID, OrganizationProviderId, CredentialReference]:
    return uuid4(), OrganizationProviderId(uuid4()), CredentialReference(uuid4())


def test_azure_store_create_replace_resolve_and_delete() -> None:
    async def scenario() -> None:
        client = FakeSecretClient()
        store = AzureKeyVaultCredentialStore(cast(SecretClient, client))
        organization_id, provider_id, reference = _scope()

        await store.put(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
            secret=ProviderCredentialSecret("first"),
        )
        await store.put(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
            secret=ProviderCredentialSecret("second"),
        )
        resolved = await store.resolve(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
        )
        assert resolved.reveal() == "second"
        assert len(client.set_calls) == 2
        assert client.set_calls[0][0] == client.set_calls[1][0]

        await store.delete(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
        )
        assert len(client.delete_calls) == 1

    asyncio.run(scenario())


def test_azure_store_maps_missing_delete_idempotently_and_missing_resolve() -> None:
    async def scenario() -> None:
        client = FakeSecretClient()
        store = AzureKeyVaultCredentialStore(cast(SecretClient, client))
        organization_id, provider_id, reference = _scope()
        missing = ResourceNotFoundError(message="provider detail")
        client.get_error = missing
        with pytest.raises(CredentialNotFoundError, match="Credential was not found"):
            await store.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )

        client.delete_error = missing
        await store.delete(
            organization_public_id=organization_id,
            provider_id=provider_id,
            credential_reference=reference,
        )

    asyncio.run(scenario())


def test_azure_store_maps_deleted_name_conflict_and_sanitizes_failures() -> None:
    async def scenario() -> None:
        client = FakeSecretClient()
        store = AzureKeyVaultCredentialStore(cast(SecretClient, client))
        organization_id, provider_id, reference = _scope()
        plaintext = "plaintext-must-not-leak"
        response = SimpleNamespace(status_code=409, reason="secret detail")
        client.set_error = HttpResponseError(
            message=f"retained name: {plaintext}",
            response=response,
        )

        with pytest.raises(CredentialStoreConflictError) as error:
            await store.put(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
                secret=ProviderCredentialSecret(plaintext),
            )
        assert plaintext not in str(error.value)
        assert "retained" not in str(error.value)

        client.set_error = HttpResponseError(message=plaintext)
        with pytest.raises(CredentialStoreError) as provider_error:
            await store.put(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
                secret=ProviderCredentialSecret(plaintext),
            )
        assert plaintext not in str(provider_error.value)

    asyncio.run(scenario())


def test_azure_store_sanitizes_resolve_and_delete_failures() -> None:
    async def scenario() -> None:
        client = FakeSecretClient()
        store = AzureKeyVaultCredentialStore(cast(SecretClient, client))
        organization_id, provider_id, reference = _scope()
        provider_detail = "credential-provider-sensitive-detail"

        client.get_error = HttpResponseError(message=provider_detail)
        with pytest.raises(CredentialStoreError) as resolve_error:
            await store.resolve(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )
        assert provider_detail not in str(resolve_error.value)

        client.delete_error = HttpResponseError(message=provider_detail)
        with pytest.raises(CredentialStoreError) as delete_error:
            await store.delete(
                organization_public_id=organization_id,
                provider_id=provider_id,
                credential_reference=reference,
            )
        assert provider_detail not in str(delete_error.value)

    asyncio.run(scenario())
