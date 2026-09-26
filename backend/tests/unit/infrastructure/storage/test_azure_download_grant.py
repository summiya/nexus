from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from azure.storage.blob import BlobSasPermissions, UserDelegationKey
from azure.storage.blob.aio import BlobServiceClient

from nexus.infrastructure.storage import azure_download_grant
from nexus.infrastructure.storage.azure_download_grant import (
    AzureUserDelegationDownloadGrantIssuer,
)

NOW = datetime(2026, 9, 26, 15, tzinfo=UTC)
EXPIRY = NOW + timedelta(minutes=5)


class FakeBlobClient:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeBlobServiceClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def get_blob_client(self, *, container: str, blob: str) -> FakeBlobClient:
        self.calls.append({"container": container, "blob": blob})
        return FakeBlobClient(f"https://storage.example/{container}/{blob}")


class FakeKeyProvider:
    def __init__(self) -> None:
        self.calls: list[datetime] = []
        self.key = cast(UserDelegationKey, object())

    async def get_key(self, *, expires_at: datetime) -> UserDelegationKey:
        self.calls.append(expires_at)
        return self.key


def _issuer(
    client: FakeBlobServiceClient,
    provider: FakeKeyProvider,
) -> AzureUserDelegationDownloadGrantIssuer:
    return AzureUserDelegationDownloadGrantIssuer(
        cast(BlobServiceClient, client),
        account_name="nexus",
        container_name="nexus-files",
        delegation_key_provider=provider,  # type: ignore[arg-type]
    )


def test_issues_exact_blob_read_only_https_attachment_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def signer(**kwargs: object) -> str:
        calls.append(kwargs)
        return "sv=2026-04-06&sp=r&sig=REDACTED"

    monkeypatch.setattr(azure_download_grant, "generate_blob_sas", signer)
    client = FakeBlobServiceClient()
    provider = FakeKeyProvider()

    grant = asyncio.run(
        _issuer(client, provider).issue_download_grant(
            storage_key="files/0123456789abcdef0123456789abcdef",
            original_name="report.pdf",
            mime_type="application/pdf",
            expires_at=EXPIRY,
        )
    )

    assert provider.calls == [EXPIRY]
    assert client.calls == [
        {
            "container": "nexus-files",
            "blob": "files/0123456789abcdef0123456789abcdef",
        }
    ]
    assert grant.expires_at is EXPIRY
    assert "sig=REDACTED" in grant.url

    call = calls[0]
    permission = cast(BlobSasPermissions, call["permission"])
    assert permission.read is True
    assert permission.write is False
    assert permission.create is False
    assert permission.delete is False
    assert call["protocol"] == "https"
    assert call["expiry"] is EXPIRY
    assert call["content_disposition"] == 'attachment; filename="report.pdf"'
    assert call["content_type"] == "application/pdf"
    assert call["blob_name"] == "files/0123456789abcdef0123456789abcdef"
    assert "account_key" not in call


def test_unicode_filename_uses_rfc5987_and_html_is_forced_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def signer(**kwargs: object) -> str:
        calls.append(kwargs)
        return "sig=REDACTED"

    monkeypatch.setattr(azure_download_grant, "generate_blob_sas", signer)

    asyncio.run(
        _issuer(FakeBlobServiceClient(), FakeKeyProvider()).issue_download_grant(
            storage_key="files/0123456789abcdef0123456789abcdef",
            original_name="رپورٹ.html",
            mime_type="text/html",
            expires_at=EXPIRY,
        )
    )

    disposition = cast(str, calls[0]["content_disposition"])
    assert disposition.startswith("attachment; ")
    assert "filename*=UTF-8''" in disposition
    assert "%D8" in disposition
    assert calls[0]["content_type"] == "text/html"


def test_missing_mime_falls_back_to_octet_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def signer(**kwargs: object) -> str:
        calls.append(kwargs)
        return "sig=REDACTED"

    monkeypatch.setattr(azure_download_grant, "generate_blob_sas", signer)

    asyncio.run(
        _issuer(FakeBlobServiceClient(), FakeKeyProvider()).issue_download_grant(
            storage_key="files/0123456789abcdef0123456789abcdef",
            original_name="file.bin",
            mime_type="",
            expires_at=EXPIRY,
        )
    )

    assert calls[0]["content_type"] == "application/octet-stream"
