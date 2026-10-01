"""Provider-neutral Document persistence boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from nexus.documents.domain import Document


class DocumentPersistenceError(Exception):
    """An unexpected Document persistence failure occurred."""


class DocumentReferenceError(DocumentPersistenceError):
    """A Document organization or source File reference is invalid."""


class DocumentConflictError(DocumentPersistenceError):
    """A Document identity, active lifecycle, or snapshot conflicts."""


class DocumentPersistence(Protocol):
    """Short transaction operations for immutable Document snapshots."""

    async def create_document(self, document: Document) -> None: ...

    async def get_document(
        self,
        *,
        organization_public_id: UUID,
        document_public_id: UUID,
    ) -> Document | None: ...

    async def update_document(
        self,
        *,
        expected: Document,
        document: Document,
    ) -> None:
        """Replace an unchanged stored snapshot with its next snapshot."""
