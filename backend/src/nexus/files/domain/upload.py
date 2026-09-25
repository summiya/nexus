"""Trusted File upload state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class FileUploadAttempt:
    """Trusted metadata retained for one issued File upload grant."""

    file_public_id: UUID
    organization_public_id: UUID
    declared_size_bytes: int
    grant_expires_at: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.declared_size_bytes, bool) or not isinstance(
            self.declared_size_bytes,
            int,
        ):
            raise TypeError("declared_size_bytes must be an integer")
        if self.declared_size_bytes < 0:
            raise ValueError("declared_size_bytes must not be negative")
        _require_timezone_aware(self.grant_expires_at, "grant_expires_at")
        _require_timezone_aware(self.created_at, "created_at")
        if self.grant_expires_at <= self.created_at:
            raise ValueError("grant_expires_at must be later than created_at")
