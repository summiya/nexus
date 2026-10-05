from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from nexus.documents.ports import DocumentInitiationConflictError
from nexus.infrastructure.persistence import document_initiation as initiation_module
from nexus.infrastructure.persistence.document_initiation import (
    SqlAlchemyDocumentInitiationPersistence,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)
STORAGE_KEY = "files/0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "changes",
    [
        {"storage_key": "invalid"},
        {"source_entity_tag": ""},
        {"source_entity_tag": " "},
        {"source_entity_tag": "x" * 1025},
        {"expected_size_bytes": -1},
        {"expected_size_bytes": True},
        {"at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_source_facts_fail_before_database_access(
    changes: dict[str, object],
) -> None:
    factory = Mock()
    persistence = SqlAlchemyDocumentInitiationPersistence(factory)
    arguments = {
        "storage_key": STORAGE_KEY,
        "source_entity_tag": "verified-v1",
        "expected_size_bytes": 42,
        "at": NOW,
    }
    arguments.update(changes)
    with pytest.raises(
        DocumentInitiationConflictError, match="^Document initiation conflicts$"
    ):
        asyncio.run(persistence.apply_clean_scan(**arguments))  # type: ignore[arg-type]
    factory.begin.assert_not_called()


def test_initiation_logs_only_outcome_and_hashed_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persistence = SqlAlchemyDocumentInitiationPersistence(Mock())
    monkeypatch.setattr(persistence, "_execute", AsyncMock(return_value="created"))
    logger = Mock()
    monkeypatch.setattr(initiation_module, "logger", logger)
    asyncio.run(
        persistence.apply_clean_scan(
            storage_key=STORAGE_KEY,
            source_entity_tag="private-version",
            expected_size_bytes=42,
            at=NOW,
        )
    )
    logger.info.assert_called_once()
    arguments = logger.info.call_args.kwargs
    assert arguments["outcome"] == "created"
    assert len(arguments["correlation"]) == 16
    assert STORAGE_KEY not in repr(logger.mock_calls)
    assert "private-version" not in repr(logger.mock_calls)
