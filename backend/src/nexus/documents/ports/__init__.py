"""Application-facing Document capability boundaries."""

from nexus.documents.ports.persistence import (
    DocumentConflictError,
    DocumentPersistence,
    DocumentPersistenceError,
    DocumentReferenceError,
)

__all__ = [
    "DocumentConflictError",
    "DocumentPersistence",
    "DocumentPersistenceError",
    "DocumentReferenceError",
]
