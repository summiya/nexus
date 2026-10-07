"""Explicit trusted reprocessing creates a generation without resetting history."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from nexus.documents.domain import Document


class DocumentReprocessingError(Exception):
    """The generation transaction failed and may be retried."""


class DocumentReprocessingConflictError(DocumentReprocessingError):
    """The expected latest terminal generation is no longer eligible."""


class DocumentReprocessing(Protocol):
    async def create_generation(
        self,
        *,
        organization_public_id: UUID,
        source_file_public_id: UUID,
        expected_document_public_id: UUID,
        at: datetime,
    ) -> Document:
        """Caller must authorize reprocessing for these trusted tenant identities."""
        ...
