"""Shared-key SAS grants for local Azure Blob-compatible development."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from urllib.parse import quote

from azure.core.exceptions import AzureError
from azure.storage.blob import BlobSasPermissions, generate_blob_sas

from nexus.files.ports import DownloadGrant, DownloadGrantError, UploadGrant, UploadGrantError

_UPLOAD_GRANT_FAILURE_MESSAGE = "The upload grant could not be issued."
_DOWNLOAD_GRANT_FAILURE_MESSAGE = "The download grant could not be issued."
_DEFAULT_CONTENT_TYPE = "application/octet-stream"
_RFC5987_SAFE = "!#$&+-.^_|~"


class AzureSharedKeyUploadGrantIssuer:
    """Issue exact-blob SAS upload grants with a local Shared Key."""

    def __init__(
        self,
        *,
        account_name: str,
        account_key: str,
        container_name: str,
        public_blob_base_url: str,
    ) -> None:
        self._account_name = _require_text(account_name)
        self._account_key = _require_text(account_key)
        self._container_name = _require_text(container_name)
        self._public_blob_base_url = public_blob_base_url.rstrip("/")
        if not self._public_blob_base_url.startswith(("http://", "https://")):
            raise ValueError("Azure public blob base URL must be HTTP(S)")

    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        storage_key = _require_text(storage_key)
        try:
            sas_token = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container_name,
                blob_name=storage_key,
                account_key=self._account_key,
                permission=BlobSasPermissions(create=True),
                expiry=expires_at,
                protocol=_sas_protocol(self._public_blob_base_url),
            )
        except (AzureError, ValueError) as exc:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE) from exc
        if not sas_token:
            raise UploadGrantError(_UPLOAD_GRANT_FAILURE_MESSAGE)
        return UploadGrant(
            url=_blob_url(
                self._public_blob_base_url,
                self._container_name,
                storage_key,
                sas_token,
            ),
            method="PUT",
            headers={"x-ms-blob-type": "BlockBlob"},
            expires_at=expires_at,
        )


class AzureSharedKeyDownloadGrantIssuer:
    """Issue exact-blob read SAS grants with a local Shared Key."""

    def __init__(
        self,
        *,
        account_name: str,
        account_key: str,
        container_name: str,
        public_blob_base_url: str,
    ) -> None:
        self._account_name = _require_text(account_name)
        self._account_key = _require_text(account_key)
        self._container_name = _require_text(container_name)
        self._public_blob_base_url = public_blob_base_url.rstrip("/")
        if not self._public_blob_base_url.startswith(("http://", "https://")):
            raise ValueError("Azure public blob base URL must be HTTP(S)")

    async def issue_download_grant(
        self,
        *,
        storage_key: str,
        original_name: str,
        mime_type: str,
        expires_at: datetime,
    ) -> DownloadGrant:
        storage_key = _require_text(storage_key)
        original_name = _require_text(original_name)
        try:
            sas_token = generate_blob_sas(
                account_name=self._account_name,
                container_name=self._container_name,
                blob_name=storage_key,
                account_key=self._account_key,
                permission=BlobSasPermissions(read=True),
                expiry=expires_at,
                protocol=_sas_protocol(self._public_blob_base_url),
                content_disposition=_attachment_content_disposition(original_name),
                content_type=_response_content_type(mime_type),
            )
        except (AzureError, ValueError) as exc:
            raise DownloadGrantError(_DOWNLOAD_GRANT_FAILURE_MESSAGE) from exc
        if not sas_token:
            raise DownloadGrantError(_DOWNLOAD_GRANT_FAILURE_MESSAGE)
        return DownloadGrant(
            url=_blob_url(
                self._public_blob_base_url,
                self._container_name,
                storage_key,
                sas_token,
            ),
            expires_at=expires_at,
        )


def _blob_url(base: str, container: str, storage_key: str, sas_token: str) -> str:
    encoded_key = quote(storage_key, safe="/~")
    return f"{base}/{quote(container, safe='')}/{encoded_key}?{sas_token}"


def _sas_protocol(base_url: str) -> str:
    return "https" if base_url.startswith("https://") else "https,http"


def _require_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Azure Shared Key configuration is invalid")
    return value.strip()


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


__all__ = [
    "AzureSharedKeyDownloadGrantIssuer",
    "AzureSharedKeyUploadGrantIssuer",
]
