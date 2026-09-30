from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobSasPermissions

from nexus.files.ports import DownloadGrantError, UploadGrantError
from nexus.infrastructure.storage import azure_shared_key_grants
from nexus.infrastructure.storage.azure_shared_key_grants import (
    AzureSharedKeyDownloadGrantIssuer,
    AzureSharedKeyUploadGrantIssuer,
)

NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)
EXPIRY = NOW + timedelta(minutes=10)


def _install_signer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: Exception | None = None,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_generate_blob_sas(**kwargs: object) -> str:
        calls.append(kwargs)
        if error is not None:
            raise error
        return "sv=2030-01-01&sig=REDACTED"

    monkeypatch.setattr(
        azure_shared_key_grants,
        "generate_blob_sas",
        fake_generate_blob_sas,
    )
    return calls


def test_local_upload_grant_is_exact_blob_create_only_and_http_capable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        calls = _install_signer(monkeypatch)
        issuer = AzureSharedKeyUploadGrantIssuer(
            account_name="devstoreaccount1",
            account_key="local-key",
            container_name="nexus-files",
            public_blob_base_url="http://localhost:10000/devstoreaccount1",
        )

        grant = await issuer.issue_upload_grant(
            storage_key="orgs/test/files/a b",
            expires_at=EXPIRY,
        )

        assert grant.method == "PUT"
        assert grant.headers == {"x-ms-blob-type": "BlockBlob"}
        assert grant.expires_at is EXPIRY
        assert grant.url.startswith(
            "http://localhost:10000/devstoreaccount1/nexus-files/orgs/test/files/a%20b?"
        )

        call = calls[0]
        assert call["account_name"] == "devstoreaccount1"
        assert call["container_name"] == "nexus-files"
        assert call["blob_name"] == "orgs/test/files/a b"
        assert call["account_key"] == "local-key"
        assert call["protocol"] == "https,http"
        permission = cast(BlobSasPermissions, call["permission"])
        assert permission.create is True
        assert permission.read is False
        assert permission.write is False
        assert permission.delete is False

    asyncio.run(scenario())


def test_local_download_grant_is_read_only_and_forces_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        calls = _install_signer(monkeypatch)
        issuer = AzureSharedKeyDownloadGrantIssuer(
            account_name="devstoreaccount1",
            account_key="local-key",
            container_name="nexus-files",
            public_blob_base_url="http://localhost:10000/devstoreaccount1",
        )

        grant = await issuer.issue_download_grant(
            storage_key="files/opaque",
            original_name="résumé.pdf",
            mime_type="application/pdf",
            expires_at=EXPIRY,
        )

        assert grant.expires_at is EXPIRY
        query = parse_qs(urlsplit(grant.url).query)
        assert query["sig"] == ["REDACTED"]

        call = calls[0]
        permission = cast(BlobSasPermissions, call["permission"])
        assert permission.read is True
        assert permission.create is False
        assert permission.write is False
        assert call["content_type"] == "application/pdf"
        assert str(call["content_disposition"]).startswith("attachment;")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("issuer_kind", "expected_error"),
    [
        ("upload", UploadGrantError),
        ("download", DownloadGrantError),
    ],
)
def test_local_signing_errors_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    issuer_kind: str,
    expected_error: type[Exception],
) -> None:
    async def scenario() -> None:
        provider_error = AzureError("sensitive local signing detail")
        _install_signer(monkeypatch, error=provider_error)

        if issuer_kind == "upload":
            issuer = AzureSharedKeyUploadGrantIssuer(
                account_name="devstoreaccount1",
                account_key="local-key",
                container_name="nexus-files",
                public_blob_base_url="http://localhost:10000/devstoreaccount1",
            )
            operation = issuer.issue_upload_grant(
                storage_key="files/opaque",
                expires_at=EXPIRY,
            )
        else:
            issuer = AzureSharedKeyDownloadGrantIssuer(
                account_name="devstoreaccount1",
                account_key="local-key",
                container_name="nexus-files",
                public_blob_base_url="http://localhost:10000/devstoreaccount1",
            )
            operation = issuer.issue_download_grant(
                storage_key="files/opaque",
                original_name="file.pdf",
                mime_type="application/pdf",
                expires_at=EXPIRY,
            )

        with pytest.raises(expected_error) as captured:
            await operation

        assert "sensitive local signing detail" not in str(captured.value)

    asyncio.run(scenario())
