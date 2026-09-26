"""Azure User Delegation SAS implementation of the download-grant boundary."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from urllib.parse import quote

from azure.core.exceptions import AzureError
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

from nexus.files.ports import DownloadGrant, DownloadGrantError
from nexus.infrastructure.storage.azure_user_delegation_key import (
    AzureUserDelegationKeyError,
    AzureUserDelegationKeyProvider,
)

_DOWNLOAD_GRANT_FAILURE_MESSAGE = "The download grant could not be issued."
_DEFAULT_CONTENT_TYPE = "application/octet-stream"
_RFC5987_SAFE = "!#$&+-.^_|~"


class AzureUserDelegationDownloadGrantIssuer:
    """Issue exact-Blob read-only HTTPS grants with forced attachment headers."""

    def __init__(
        self,
        service_client: BlobServiceClient,
        *,
        account_name: str,
        container_name: str,
        delegation_key_provider: AzureUserDelegationKeyProvider,
    ) -> None:
        if not isinstance(account_name, str) or not account_name.strip():
            raise ValueError("Azure storage account name must not be blank")
        if not isinstance(container_name, str) or not container_name.strip():
            raise ValueError("Azure storage container name must not be blank")

        self._service_client = service_client
        self._account_name = account_name
        self._container_name = container_name
        self._delegation_key_provider = delegation_key_provider

    async def issue_download_grant(
        self,
        *,
        storage_key: str,
        original_name: str,
        mime_type: str,
        expires_at: datetime,
    ) -> DownloadGrant:
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise ValueError("Storage key must not be blank")
        if not isinstance(original_name, str) or not original_name.strip():
            raise ValueError("Original name must not be blank")

        try:
            delegation_key = await self._delegation_key_provider.get_key(
                expires_at=expires_at
            )
        except AzureUserDelegationKeyError as exc:
            raise DownloadGrantError(_DOWNLOAD_GRANT_FAILURE_MESSAGE) from exc

        blob_client = self._service_client.get_blob_client(
            container=self._container_name,
            blob=storage_key,
        )
        content_type = _response_content_type(mime_type)
        content_disposition = _attachment_content_disposition(original_name)

        try:
            sas_token = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container_name,
                blob_name=storage_key,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(read=True),
                expiry=expires_at,
                protocol="https",
                content_disposition=content_disposition,
                content_type=content_type,
            )
        except (AzureError, ValueError) as exc:
            raise DownloadGrantError(_DOWNLOAD_GRANT_FAILURE_MESSAGE) from exc

        if not isinstance(sas_token, str) or not sas_token:
            raise DownloadGrantError(_DOWNLOAD_GRANT_FAILURE_MESSAGE)

        return DownloadGrant(
            url=f"{blob_client.url}?{sas_token}",
            expires_at=expires_at,
        )


def _attachment_content_disposition(original_name: str) -> str:
    fallback = _ascii_filename_fallback(original_name)
    escaped_fallback = fallback.replace("\\", "\\\\").replace('"', '\\"')
    if original_name.isascii():
        return f'attachment; filename="{escaped_fallback}"'

    encoded = quote(original_name, safe=_RFC5987_SAFE, encoding="utf-8")
    return f"attachment; filename=\"{escaped_fallback}\"; filename*=UTF-8''{encoded}"


def _ascii_filename_fallback(original_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", original_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    safe_name = "".join(
        character if " " <= character <= "~" else "_" for character in ascii_name
    ).strip()
    if safe_name.startswith(".") and len(safe_name) > 1:
        return f"download{safe_name}"
    return safe_name or "download"


def _response_content_type(mime_type: str) -> str:
    if (
        not isinstance(mime_type, str)
        or not mime_type.strip()
        or "\r" in mime_type
        or "\n" in mime_type
    ):
        return _DEFAULT_CONTENT_TYPE
    return mime_type.strip()


__all__ = ["AzureUserDelegationDownloadGrantIssuer"]
