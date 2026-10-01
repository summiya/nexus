"""Provider-neutral Document domain contracts."""

from nexus.documents.domain.document import (
    Document,
    DocumentDomainError,
    DocumentFailure,
    DocumentStatus,
    DocumentTransitionError,
)

__all__ = [
    "Document",
    "DocumentDomainError",
    "DocumentFailure",
    "DocumentStatus",
    "DocumentTransitionError",
]
