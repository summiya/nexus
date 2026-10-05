"""Source metadata and safe failures, independent of storage providers."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, repr=False)
class DocumentSourceFacts:
    source_file_public_id: UUID
    source_entity_tag: str
    expected_size_bytes: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_file_public_id, UUID)
            or self.source_file_public_id.int == 0
        ):
            raise ValueError("Invalid source File identity")
        if (
            not isinstance(self.source_entity_tag, str)
            or not self.source_entity_tag.strip()
            or len(self.source_entity_tag) > 1024
        ):
            raise ValueError("Invalid source version")
        if type(self.expected_size_bytes) is not int or self.expected_size_bytes < 0:
            raise ValueError("Invalid source size")


class DocumentSourceFailure(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    CHANGED = "changed"
    TOO_LARGE = "too_large"
    TRANSIENT_STORAGE = "transient_storage"
    STORAGE_ACCESS = "storage_access"
    STORAGE_FAILURE = "storage_failure"


class DocumentSourceError(Exception):
    def __init__(self, reason: DocumentSourceFailure) -> None:
        super().__init__("Document source access failed")
        self.reason = reason


@dataclass(frozen=True, repr=False)
class DocumentSource:
    source_file_public_id: UUID
    original_name: str
    mime_type: str
    entity_tag: str
    expected_size_bytes: int
    content: AsyncIterator[bytes] = field(repr=False)
