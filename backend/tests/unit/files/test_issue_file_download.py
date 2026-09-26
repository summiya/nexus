from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.files.application import IssueFileDownload
from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import DownloadGrant, DownloadGrantError

NOW = datetime(2026, 9, 26, 15, tzinfo=UTC)
URL = "https://storage.example/file?sig=SENSITIVE"


class FakeGetFile:
    def __init__(self, file: File) -> None:
        self.file = file
        self.error: NexusError | None = None

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> File:
        del organization_public_id, user_public_id, file_public_id
        if self.error is not None:
            raise self.error
        return self.file


class FakeDownloadGrantIssuer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    async def issue_download_grant(
        self,
        *,
        storage_key: str,
        original_name: str,
        mime_type: str,
        expires_at: datetime,
    ) -> DownloadGrant:
        self.calls.append(
            {
                "storage_key": storage_key,
                "original_name": original_name,
                "mime_type": mime_type,
                "expires_at": expires_at,
            }
        )
        if self.error is not None:
            raise self.error
        return DownloadGrant(url=URL, expires_at=expires_at)


def _file(status: FileStorageStatus = FileStorageStatus.AVAILABLE) -> File:
    return File(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=42,
        storage_key=f"files/{uuid4().hex}",
        storage_status=status,
        checksum_sha256=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _service(file: File, issuer: FakeDownloadGrantIssuer) -> IssueFileDownload:
    return IssueFileDownload(
        get_file=FakeGetFile(file),  # type: ignore[arg-type]
        download_grant_issuer=issuer,  # type: ignore[arg-type]
        grant_ttl=timedelta(minutes=5),
        clock=lambda: NOW,
    )


def test_available_file_gets_short_lived_download_grant() -> None:
    file = _file()
    issuer = FakeDownloadGrantIssuer()

    grant = asyncio.run(
        _service(file, issuer).execute(
            organization_public_id=file.organization_public_id,
            user_public_id=file.created_by_user_public_id,
            file_public_id=file.public_id,
        )
    )

    assert grant.url == URL
    assert grant.expires_at == NOW + timedelta(minutes=5)
    assert issuer.calls == [
        {
            "storage_key": file.storage_key,
            "original_name": "report.pdf",
            "mime_type": "application/pdf",
            "expires_at": NOW + timedelta(minutes=5),
        }
    ]


@pytest.mark.parametrize(
    "status",
    [FileStorageStatus.PENDING, FileStorageStatus.FAILED],
)
def test_unavailable_file_is_rejected_without_grant(status: FileStorageStatus) -> None:
    file = _file(status)
    issuer = FakeDownloadGrantIssuer()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _service(file, issuer).execute(
                organization_public_id=file.organization_public_id,
                user_public_id=file.created_by_user_public_id,
                file_public_id=file.public_id,
            )
        )

    assert captured.value.code is ErrorCode.CONFLICT
    assert issuer.calls == []


@pytest.mark.parametrize("code", [ErrorCode.NOT_FOUND, ErrorCode.FORBIDDEN])
def test_get_file_security_failures_propagate_without_grant(code: ErrorCode) -> None:
    file = _file()
    issuer = FakeDownloadGrantIssuer()
    get_file = FakeGetFile(file)
    get_file.error = NexusError(code, "safe")
    service = IssueFileDownload(
        get_file=get_file,  # type: ignore[arg-type]
        download_grant_issuer=issuer,  # type: ignore[arg-type]
        grant_ttl=timedelta(minutes=5),
        clock=lambda: NOW,
    )

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            service.execute(
                organization_public_id=file.organization_public_id,
                user_public_id=file.created_by_user_public_id,
                file_public_id=file.public_id,
            )
        )

    assert captured.value.code is code
    assert issuer.calls == []


def test_provider_failure_returns_safe_error_without_bearer_link() -> None:
    file = _file()
    issuer = FakeDownloadGrantIssuer()
    issuer.error = DownloadGrantError(f"provider failed {URL}")

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _service(file, issuer).execute(
                organization_public_id=file.organization_public_id,
                user_public_id=file.created_by_user_public_id,
                file_public_id=file.public_id,
            )
        )

    assert captured.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert URL not in str(captured.value)
    assert file.storage_key not in str(captured.value)
