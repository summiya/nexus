"""Provider-neutral committed-upload event contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from nexus.files.domain import is_canonical_file_storage_key

_MAX_EVENT_ID_LENGTH = 1024
_MAX_SOURCE_LENGTH = 1024
_MAX_STORAGE_KEY_LENGTH = 1024
_MAX_ENTITY_TAG_LENGTH = 1024


def _require_nonblank_bounded(
    value: object,
    field_name: str,
    maximum: int,
) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if len(value) > maximum or not value.strip():
        raise ValueError(f"{field_name} is invalid")


@dataclass(frozen=True, repr=False)
class UploadCompletionEvent:
    """Trusted provider-neutral facts reported for one committed object."""

    event_id: str
    source: str
    storage_key: str
    occurred_at: datetime
    entity_tag: str
    reported_size_bytes: int

    def __post_init__(self) -> None:
        _require_nonblank_bounded(
            self.event_id,
            "event_id",
            _MAX_EVENT_ID_LENGTH,
        )
        _require_nonblank_bounded(self.source, "source", _MAX_SOURCE_LENGTH)
        _require_nonblank_bounded(
            self.storage_key,
            "storage_key",
            _MAX_STORAGE_KEY_LENGTH,
        )
        if not is_canonical_file_storage_key(self.storage_key):
            raise ValueError("storage_key is invalid")
        _require_nonblank_bounded(
            self.entity_tag,
            "entity_tag",
            _MAX_ENTITY_TAG_LENGTH,
        )
        if (
            not isinstance(self.occurred_at, datetime)
            or self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must be timezone-aware")
        if isinstance(self.reported_size_bytes, bool) or not isinstance(
            self.reported_size_bytes,
            int,
        ):
            raise TypeError("reported_size_bytes must be an integer")
        if self.reported_size_bytes < 0:
            raise ValueError("reported_size_bytes must not be negative")


class UploadCompletionHandler(Protocol):
    """Apply one committed-upload event at the File application boundary.

    The Phase 14 implementation must perform slow external work, including
    Blob access, Key Vault calls, and UploadContext decryption, without
    holding a database transaction. It must then apply the File business
    effect in one short database transaction protected by INV-REL-004.
    """

    async def handle(self, event: UploadCompletionEvent) -> None: ...


__all__ = ["UploadCompletionEvent", "UploadCompletionHandler"]
