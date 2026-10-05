from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.documents.application.initiation import initial_document
from nexus.documents.domain import DocumentStatus
from nexus.files.domain import File, FileStorageStatus

NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _file(name: str, mime: str) -> File:
    return File(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        original_name=name,
        mime_type=mime,
        size_bytes=0,
        storage_key=f"files/{uuid4().hex}",
        storage_status=FileStorageStatus.AVAILABLE,
        checksum_sha256=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    ("name", "mime", "eligible"),
    [
        ("report.PDF", "application/pdf", True),
        ("report.pdf", "application/octet-stream", True),
        ("report.txt", "text/plain", True),
        ("report.txt", "application/octet-stream", True),
        ("report.md", "text/markdown", True),
        ("report.md", "text/plain", True),
        ("report.md", "application/octet-stream", True),
        ("report.pdf", "text/plain", False),
        ("report.txt", "application/pdf", False),
        ("report.md", "text/html", False),
        ("report.csv", "text/plain", False),
        ("report", "text/plain", False),
    ],
)
def test_initial_admission(name: str, mime: str, eligible: bool) -> None:
    file = _file(name, mime)
    document = initial_document(file, at=NOW)
    assert (document is not None) is eligible
    if document is not None:
        assert document.status is DocumentStatus.QUEUED
        assert document.organization_public_id == file.organization_public_id
        assert document.source_file_public_id == file.public_id
        assert document.processing_version is None
        assert document.extractor_version is None


@pytest.mark.parametrize(
    "status",
    [FileStorageStatus.PENDING, FileStorageStatus.FAILED, FileStorageStatus.DELETING],
)
def test_unavailable_files_are_ineligible(status: FileStorageStatus) -> None:
    assert (
        initial_document(
            replace(_file("report.pdf", "application/pdf"), storage_status=status),
            at=NOW,
        )
        is None
    )
