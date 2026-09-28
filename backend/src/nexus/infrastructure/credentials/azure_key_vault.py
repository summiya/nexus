"""Azure Key Vault implementation of provider credential storage."""

from __future__ import annotations

from uuid import UUID

from azure.core.exceptions import AzureError, HttpResponseError, ResourceNotFoundError
from azure.keyvault.secrets.aio import SecretClient

from nexus.model_providers.domain import (
    CredentialReference,
    OrganizationProviderId,
    ProviderCredentialSecret,
)
from nexus.model_providers.ports import (
    CredentialNotFoundError,
    CredentialStoreConflictError,
    CredentialStoreError,
    credential_storage_name,
)


class AzureKeyVaultCredentialStore:
    """Store credentials as versioned Azure Key Vault secrets."""

    def __init__(self, secret_client: SecretClient) -> None:
        self._secret_client = secret_client

    async def put(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
        secret: ProviderCredentialSecret,
    ) -> None:
        name = self._name(
            organization_public_id,
            provider_id,
            credential_reference,
        )
        try:
            await self._secret_client.set_secret(name, secret.reveal())
        except HttpResponseError as exc:
            if exc.status_code == 409:
                raise CredentialStoreConflictError(
                    "Credential reference cannot be reused."
                ) from None
            raise CredentialStoreError("Credential could not be stored.") from None
        except AzureError:
            raise CredentialStoreError("Credential could not be stored.") from None

    async def resolve(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> ProviderCredentialSecret:
        name = self._name(
            organization_public_id,
            provider_id,
            credential_reference,
        )
        try:
            resolved = await self._secret_client.get_secret(name)
        except ResourceNotFoundError:
            raise CredentialNotFoundError("Credential was not found.") from None
        except AzureError:
            raise CredentialStoreError("Credential could not be resolved.") from None
        if not isinstance(resolved.value, str) or not resolved.value.strip():
            raise CredentialStoreError("Credential could not be resolved.")
        return ProviderCredentialSecret(resolved.value)

    async def delete(
        self,
        *,
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> None:
        name = self._name(
            organization_public_id,
            provider_id,
            credential_reference,
        )
        try:
            await self._secret_client.delete_secret(name)
        except ResourceNotFoundError:
            return
        except AzureError:
            raise CredentialStoreError("Credential could not be deleted.") from None

    @staticmethod
    def _name(
        organization_public_id: UUID,
        provider_id: OrganizationProviderId,
        credential_reference: CredentialReference,
    ) -> str:
        return credential_storage_name(
            organization_public_id=organization_public_id,
            provider_id=provider_id,
            credential_reference=credential_reference,
        )
