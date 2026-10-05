"""Application-facing Document capability boundaries."""

from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
    DocumentExtractor,
)
from nexus.documents.ports.initiation import (
    DocumentInitiationConflictError,
    DocumentInitiationError,
    DocumentInitiationPersistence,
)
from nexus.documents.ports.persistence import (
    DocumentConflictError,
    DocumentPersistence,
    DocumentPersistenceError,
    DocumentReferenceError,
)

__all__ = [
    "DocumentConflictError",
    "DocumentExtractionError",
    "DocumentExtractionFailure",
    "DocumentExtractor",
    "DocumentInitiationConflictError",
    "DocumentInitiationError",
    "DocumentInitiationPersistence",
    "DocumentPersistence",
    "DocumentPersistenceError",
    "DocumentReferenceError",
]
