"""Provider-neutral Document domain contracts."""

from nexus.documents.domain.document import (
    Document,
    DocumentDomainError,
    DocumentFailure,
    DocumentStatus,
    DocumentTransitionError,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
    ExtractedListItem,
)

__all__ = [
    "Document",
    "DocumentDomainError",
    "DocumentFailure",
    "DocumentStatus",
    "DocumentTransitionError",
    "ExtractedBlock",
    "ExtractedBlockKind",
    "ExtractedDocument",
    "ExtractedListItem",
]
