"""Azure User Delegation SAS implementation of the upload-grant boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from azure.core.exceptions import AzureError
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

from nexus.files.ports import UploadGrant, UploadGrantError
from nexus.infrastructure.storage.azure_user_delegation_key import (
    AzureUserDelegationKeyError,
    AzureUserDelegationKeyProvider,
)

_UPLOAD_GRANT_FAILURE_MESSAGE = "The upload grant could not be issued."


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AzureUserDelegationUploadGrantIssuer:
    """Issue exact-Blob upload grants using a borrowed Azure service client."""

    def __init__(
        self,
        service_client: BlobServiceClient,
        *,
        account_name: str,
        container_name: str,
        delegation_key_provider: AzureUserDelegationKeyProvider | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(account_name, str) or not account_name.strip():
            raise ValueError("Azure storage account name must not be blank")
        if not isinstance(container_name, str) or not container_name.strip():
            raise ValueError("Azure storage container name must not be blank")

        self._service_client = service_client
        self._account_name = account_name
        self._container_name = container_name
        self._delegation_key_provider = (
            delegation_key_provider
            if delegation_key_provider is not None
            else AzureUserDelegationKeyProvider(service_client, clock=clock)
        )

    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        """Issue a create-only HTTPS grant for one exact Block Blob."""
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise ValueError("Storage key must not be blank")

        try:
            delegation_key = await self._delegation_key_provider.get_key(
                expires_at=expires_at
            )
        except AzureUserDelegationKeyError as exc:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE) from exc

        blob_client = self._service_client.get_blob_client(
            container=self._container_name,
            blob=storage_key,
        )

        try:
            sas_token = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container_name,
                blob_name=storage_key,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(create=True),
                expiry=expires_at,
                protocol="https",
            )
        except (AzureError, ValueError) as exc:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE) from exc

        if not isinstance(sas_token, str) or not sas_token:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE)

        return UploadGrant(
            url=f"{blob_client.url}?{sas_token}",
            method="PUT",
            headers={"x-ms-blob-type": "BlockBlob"},
            expires_at=expires_at,
        )


__all__ = ["AzureUserDelegationUploadGrantIssuer"]
