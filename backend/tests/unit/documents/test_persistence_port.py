from __future__ import annotations

import inspect

from nexus.documents.ports import (
    DocumentConflictError,
    DocumentPersistence,
    DocumentPersistenceError,
    DocumentReferenceError,
)


def test_document_persistence_exposes_only_focused_async_operations() -> None:
    operations = {
        name
        for name, value in inspect.getmembers(
            DocumentPersistence,
            predicate=inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }

    assert operations == {"create_document", "get_document", "update_document"}


def test_document_persistence_errors_share_one_capability_boundary() -> None:
    assert issubclass(DocumentReferenceError, DocumentPersistenceError)
    assert issubclass(DocumentConflictError, DocumentPersistenceError)
