"""Trusted metadata authorized for one prospective File upload."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.files.domain.file import MAX_MIME_TYPE_LENGTH, MAX_ORIGINAL_NAME_LENGTH

UPLOAD_CONTEXT_VERSION = 1
_MAX_STORAGE_KEY_LENGTH = 1024


def _require_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be a UUID")


def _require_nonblank_bounded(
    value: object,
    field_name: str,
    maximum: int,
) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} is invalid")


def _require_timezone_aware(value: object, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, repr=False)
class UploadContext:
    """Provider-neutral trusted context carried with a committed object."""

    version: int
    file_public_id: UUID
    organization_public_id: UUID
    created_by_user_public_id: UUID
    storage_key: str
    original_name: str
    mime_type: str
    declared_size_bytes: int
    issued_at: datetime
    grant_expires_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version != UPLOAD_CONTEXT_VERSION
        ):
            raise ValueError("Upload context version is unsupported")
        _require_uuid(self.file_public_id, "file_public_id")
        _require_uuid(self.organization_public_id, "organization_public_id")
        _require_uuid(
            self.created_by_user_public_id,
            "created_by_user_public_id",
        )
        _require_nonblank_bounded(
            self.storage_key,
            "storage_key",
            _MAX_STORAGE_KEY_LENGTH,
        )
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
        if isinstance(self.declared_size_bytes, bool) or not isinstance(
            self.declared_size_bytes,
            int,
        ):
            raise TypeError("declared_size_bytes must be an integer")
        if self.declared_size_bytes < 0:
            raise ValueError("declared_size_bytes must not be negative")
        _require_timezone_aware(self.issued_at, "issued_at")
        _require_timezone_aware(self.grant_expires_at, "grant_expires_at")
        if self.grant_expires_at <= self.issued_at:
            raise ValueError("grant_expires_at must be later than issued_at")


__all__ = ["UPLOAD_CONTEXT_VERSION", "UploadContext"]
