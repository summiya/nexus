"""Atomic initial ingestion boundary for trusted clean-scan facts."""

from datetime import datetime
from typing import Protocol


class DocumentInitiationError(Exception):
    """Initial ingestion failed and may be retried."""


class DocumentInitiationConflictError(DocumentInitiationError):
    """Verified source facts conflict with authoritative stored state."""


class DocumentInitiationPersistence(Protocol):
    """Commit File availability, initial Document, and request together.

    The storage key must come from the trusted, verified malware-scan handoff.
    Ownership is resolved from the File, never supplied by a client.
    """

    async def apply_clean_scan(
        self,
        *,
        storage_key: str,
        source_entity_tag: str,
        expected_size_bytes: int,
        at: datetime,
    ) -> None: ...
