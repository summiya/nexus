"""Authorize and issue one short-lived direct File download."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nexus.errors import ErrorCode, NexusError
from nexus.files.application.get_file import GetFile
from nexus.files.domain import FileStorageStatus
from nexus.files.ports import DownloadGrant, DownloadGrantError, DownloadGrantIssuer
from nexus.logging import get_logger

_DOWNLOAD_UNAVAILABLE_MESSAGE = "The file download could not be initiated."
_FILE_NOT_AVAILABLE_MESSAGE = "The file is not available for download."
_SAFE_CORRELATION_LENGTH = 16

logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class IssueFileDownload:
    """Authorize one File and issue an ephemeral direct-download capability."""

    get_file: GetFile
    download_grant_issuer: DownloadGrantIssuer
    grant_ttl: timedelta
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        if not isinstance(self.grant_ttl, timedelta):
            raise TypeError("grant_ttl must be a positive timedelta")
        if self.grant_ttl <= timedelta(0):
            raise ValueError("grant_ttl must be a positive timedelta")

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> DownloadGrant:
        file = await self.get_file.execute(
            organization_public_id=organization_public_id,
            user_public_id=user_public_id,
            file_public_id=file_public_id,
        )
        if file.storage_status is not FileStorageStatus.AVAILABLE:
            raise NexusError(
                ErrorCode.CONFLICT,
                _FILE_NOT_AVAILABLE_MESSAGE,
            )

        issued_at = self._current_time()
        requested_expiration = issued_at + self.grant_ttl
        correlation = _safe_correlation(
            organization_public_id=organization_public_id,
            file_public_id=file_public_id,
        )
        try:
            grant = await self.download_grant_issuer.issue_download_grant(
                storage_key=file.storage_key,
                original_name=file.original_name,
                mime_type=file.mime_type,
                expires_at=requested_expiration,
            )
        except DownloadGrantError as exc:
            logger.warning(
                "file_download_grant_issue_failed",
                correlation=correlation,
            )
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                _DOWNLOAD_UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from exc

        validated_at = self._current_time()
        if (
            not _is_timezone_aware(grant.expires_at)
            or grant.expires_at <= validated_at
            or grant.expires_at > requested_expiration
        ):
            logger.warning(
                "file_download_grant_invalid_expiration",
                correlation=correlation,
            )
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                _DOWNLOAD_UNAVAILABLE_MESSAGE,
                retryable=True,
            )

        logger.info(
            "file_download_grant_issued",
            correlation=correlation,
        )
        return grant

    def _current_time(self) -> datetime:
        now = self.clock()
        if not _is_timezone_aware(now):
            raise ValueError("Download initiation clock must be timezone-aware")
        return now


def _is_timezone_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _safe_correlation(
    *,
    organization_public_id: UUID,
    file_public_id: UUID,
) -> str:
    value = f"{organization_public_id}\0{file_public_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_SAFE_CORRELATION_LENGTH]


__all__ = ["IssueFileDownload"]
