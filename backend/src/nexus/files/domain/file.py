"""File domain contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

MAX_ORIGINAL_NAME_LENGTH = 255
MAX_MIME_TYPE_LENGTH = 255
_MAX_STORAGE_KEY_LENGTH = 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_FILE_STORAGE_KEY_PATTERN = re.compile(
    r"files/[0-9a-f]{32}",
    re.ASCII,
)


class FileStorageStatus(StrEnum):
    """Lifecycle of a File's binary object in configured storage."""

    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"
    DELETING = "deleting"


def is_canonical_file_storage_key(value: object) -> bool:
    """Return whether a value uses Nexus's canonical File object-key syntax."""
    return (
        isinstance(value, str)
        and _CANONICAL_FILE_STORAGE_KEY_PATTERN.fullmatch(value) is not None
    )


def _require_nonblank_bounded(value: str, field_name: str, maximum: int) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} must not exceed {maximum} characters")


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class File:
    """A tenant-owned binary object and its provider-neutral storage metadata."""

    public_id: UUID
    organization_public_id: UUID
    created_by_user_public_id: UUID
    original_name: str
    mime_type: str
    size_bytes: int | None
    storage_key: str
    storage_status: FileStorageStatus
    checksum_sha256: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_nonblank_bounded(
            self.original_name,
            "original_name",
            MAX_ORIGINAL_NAME_LENGTH,
        )
        _require_nonblank_bounded(
            self.mime_type,
            "mime_type",
            MAX_MIME_TYPE_LENGTH,
        )
        _require_nonblank_bounded(
            self.storage_key,
            "storage_key",
            _MAX_STORAGE_KEY_LENGTH,
        )
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        if (
            self.storage_status is FileStorageStatus.AVAILABLE
            and self.size_bytes is None
        ):
            raise ValueError("available File must have a size")
        if (
            self.checksum_sha256 is not None
            and _SHA256_PATTERN.fullmatch(self.checksum_sha256) is None
        ):
            raise ValueError(
                "checksum_sha256 must be 64 lowercase hexadecimal characters"
            )
        _require_timezone_aware(self.created_at, "created_at")
        _require_timezone_aware(self.updated_at, "updated_at")
