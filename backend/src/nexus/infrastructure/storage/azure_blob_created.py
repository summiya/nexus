"""Map Azure BlobCreated CloudEvents into the File completion boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from nexus.files.domain import is_canonical_file_storage_key
from nexus.files.ports import UploadCompletionEvent

_INVALID_EVENT_MESSAGE = "Azure BlobCreated event is invalid."
_CLOUD_EVENT_SPEC_VERSION = "1.0"
_BLOB_CREATED_EVENT_TYPE = "Microsoft.Storage.BlobCreated"
_SUPPORTED_APIS = frozenset({"PutBlob", "PutBlockList"})
_MAX_EVENT_ID_LENGTH = 1024
_MAX_SOURCE_LENGTH = 1024
_MAX_SUBJECT_LENGTH = 4096
_MAX_ENTITY_TAG_LENGTH = 1024
_MAX_NEXUS_SOURCE_LENGTH = 1024
_MAX_CONTAINER_LENGTH = 63


class AzureBlobCreatedEventMappingError(ValueError):
    """An Azure BlobCreated payload failed strict infrastructure validation."""


@dataclass(frozen=True)
class AzureBlobCreatedEventMapper:
    """Validate one Azure CloudEvent and expose provider-neutral upload facts."""

    expected_source: str
    expected_container: str
    nexus_source: str

    def __post_init__(self) -> None:
        _require_text(self.expected_source, _MAX_SOURCE_LENGTH)
        _require_text(self.expected_container, _MAX_CONTAINER_LENGTH)
        _require_text(self.nexus_source, _MAX_NEXUS_SOURCE_LENGTH)
        if "/" in self.expected_container:
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)

    def map_event(self, payload: Mapping[str, object]) -> UploadCompletionEvent:
        """Map an already-decoded CloudEvents 1.0 BlobCreated payload."""
        event = _require_mapping(payload)
        if event.get("specversion") != _CLOUD_EVENT_SPEC_VERSION:
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
        if event.get("type") != _BLOB_CREATED_EVENT_TYPE:
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
        if event.get("source") != self.expected_source:
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)

        event_id = _require_text(event.get("id"), _MAX_EVENT_ID_LENGTH)
        subject = _require_text(event.get("subject"), _MAX_SUBJECT_LENGTH)
        occurred_at = _parse_timestamp(event.get("time"))
        data = _require_mapping(event.get("data"))

        if data.get("api") not in _SUPPORTED_APIS:
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
        if data.get("blobType") != "BlockBlob":
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)

        entity_tag = _require_text(data.get("eTag"), _MAX_ENTITY_TAG_LENGTH)
        reported_size_bytes = data.get("contentLength")
        if isinstance(reported_size_bytes, bool) or not isinstance(
            reported_size_bytes,
            int,
        ):
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
        if reported_size_bytes < 0:
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)

        storage_key = self._storage_key_from_subject(subject)
        return UploadCompletionEvent(
            event_id=event_id,
            source=self.nexus_source,
            storage_key=storage_key,
            occurred_at=occurred_at,
            entity_tag=entity_tag,
            reported_size_bytes=reported_size_bytes,
        )

    def _storage_key_from_subject(self, subject: str) -> str:
        prefix = f"/blobServices/default/containers/{self.expected_container}/blobs/"
        if not subject.startswith(prefix):
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)

        storage_key = subject.removeprefix(prefix)
        if not is_canonical_file_storage_key(storage_key):
            raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
        return storage_key


def _require_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
    return cast(Mapping[str, object], value)


def _require_text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or not value.strip():
        raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
    return value


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)

    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AzureBlobCreatedEventMappingError(_INVALID_EVENT_MESSAGE)
    return parsed


__all__ = [
    "AzureBlobCreatedEventMapper",
    "AzureBlobCreatedEventMappingError",
]
