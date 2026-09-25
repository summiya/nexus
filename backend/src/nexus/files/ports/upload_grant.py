"""Provider-neutral direct-upload grant boundary for the File capability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Protocol


class UploadGrantError(Exception):
    """An unexpected upload-grant issuance failure occurred."""


@dataclass(frozen=True)
class UploadGrant:
    """Short-lived browser instructions for one exact, create-only object upload."""

    url: str = field(repr=False)
    method: str
    headers: Mapping[str, str] = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("Upload grant URL must not be blank")

        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("Upload grant HTTP method must not be blank")
        object.__setattr__(self, "method", self.method.strip().upper())

        frozen_headers = dict(self.headers)
        for name, value in frozen_headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise TypeError("Upload grant headers must use string names and values")
            if not name.strip():
                raise ValueError("Upload grant header names must not be blank")
        object.__setattr__(self, "headers", MappingProxyType(frozen_headers))

        if (
            not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("Upload grant expiration must be timezone-aware")


class UploadGrantIssuer(Protocol):
    """Issue an exact-object, create-only upload capability."""

    async def issue_upload_grant(
        self,
        *,
        storage_key: str,
        expires_at: datetime,
    ) -> UploadGrant:
        """Issue instructions that expire no later than the requested timestamp."""


__all__ = ["UploadGrant", "UploadGrantError", "UploadGrantIssuer"]
