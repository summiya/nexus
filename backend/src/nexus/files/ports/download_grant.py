"""Provider-neutral direct-download grant boundary for the File capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class DownloadGrantError(Exception):
    """An unexpected download-grant issuance failure occurred."""


@dataclass(frozen=True)
class DownloadGrant:
    """Short-lived browser capability for one exact File object."""

    url: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("Download grant URL must not be blank")
        if (
            not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("Download grant expiration must be timezone-aware")


class DownloadGrantIssuer(Protocol):
    """Issue an exact-object, read-only direct-download capability."""

    async def issue_download_grant(
        self,
        *,
        storage_key: str,
        original_name: str,
        mime_type: str,
        expires_at: datetime,
    ) -> DownloadGrant:
        """Issue a short-lived grant for one exact stored object."""


__all__ = ["DownloadGrant", "DownloadGrantError", "DownloadGrantIssuer"]
