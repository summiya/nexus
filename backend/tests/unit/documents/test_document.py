from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from nexus.documents.domain import (
    Document,
    DocumentDomainError,
    DocumentFailure,
    DocumentStatus,
    DocumentTransitionError,
)

CREATED_AT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
STARTED_AT = CREATED_AT + timedelta(minutes=1)
FINISHED_AT = STARTED_AT + timedelta(minutes=2)


def _document() -> Document:
    return Document(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        source_file_public_id=uuid4(),
        created_at=CREATED_AT,
    )


def _processing() -> Document:
    return _document().start_processing(at=STARTED_AT, processing_version="v1")


def test_document_starts_queued_with_authoritative_identities() -> None:
    document = _document()

    assert document.status is DocumentStatus.QUEUED
    assert all(
        isinstance(value, UUID)
        for value in (
            document.public_id,
            document.organization_public_id,
            document.source_file_public_id,
        )
    )
    assert document.processing_version is None
    assert document.processing_started_at is None


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        (field_name, invalid)
        for field_name in (
            "public_id",
            "organization_public_id",
            "source_file_public_id",
        )
        for invalid in (None, "", UUID(int=0))
    ],
)
def test_document_rejects_invalid_identity(field_name: str, invalid: object) -> None:
    with pytest.raises(DocumentDomainError, match="identifier is invalid"):
        replace(_document(), **{field_name: cast(UUID, invalid)})


def test_completed_lifecycle_records_versions_and_preserves_identity() -> None:
    queued = _document()
    processing = queued.start_processing(
        at=STARTED_AT,
        processing_version="pipeline-v1",
    )
    extracted = processing.record_extractor_version("pdf-v2")
    completed = extracted.complete(at=FINISHED_AT)

    assert processing.processing_version == "pipeline-v1"
    assert processing.extractor_version is None
    assert extracted.extractor_version == "pdf-v2"
    assert completed.status is DocumentStatus.COMPLETED
    assert completed.processing_started_at == STARTED_AT
    assert completed.processing_completed_at == FINISHED_AT
    assert (
        completed.public_id,
        completed.organization_public_id,
        completed.source_file_public_id,
    ) == (
        queued.public_id,
        queued.organization_public_id,
        queued.source_file_public_id,
    )
    assert queued.status is DocumentStatus.QUEUED


def test_processing_can_complete_without_using_an_extractor() -> None:
    completed = _processing().complete(at=FINISHED_AT)

    assert completed.status is DocumentStatus.COMPLETED
    assert completed.extractor_version is None


def test_failed_lifecycle_records_only_safe_failure_metadata() -> None:
    failed = _processing().fail(
        at=FINISHED_AT,
        code="UNSUPPORTED_FORMAT",
        safe_message="This file format is not supported.",
    )

    assert failed.status is DocumentStatus.FAILED
    assert failed.failed_at == FINISHED_AT
    assert failed.processing_completed_at is None
    assert failed.failure == DocumentFailure(
        "UNSUPPORTED_FORMAT",
        "This file format is not supported.",
    )


def test_invalid_and_repeated_transitions_fail_closed() -> None:
    queued = _document()
    with pytest.raises(DocumentTransitionError, match="cannot be completed"):
        queued.complete(at=FINISHED_AT)
    with pytest.raises(DocumentTransitionError, match="cannot fail"):
        queued.fail(at=FINISHED_AT, code="PROCESSING_FAILED", safe_message="Failed.")

    completed = _processing().complete(at=FINISHED_AT)
    failed = _processing().fail(
        at=FINISHED_AT,
        code="PROCESSING_FAILED",
        safe_message="Failed.",
    )
    for terminal in (completed, failed):
        with pytest.raises(DocumentTransitionError, match="cannot start processing"):
            terminal.start_processing(at=FINISHED_AT, processing_version="v2")
        with pytest.raises(DocumentTransitionError):
            terminal.complete(at=FINISHED_AT)
        with pytest.raises(DocumentTransitionError):
            terminal.fail(
                at=FINISHED_AT,
                code="PROCESSING_FAILED",
                safe_message="Failed.",
            )


def test_extractor_version_is_optional_then_can_be_recorded_only_once() -> None:
    with pytest.raises(DocumentTransitionError, match="only be recorded"):
        _document().record_extractor_version("extractor-v1")

    processing = _processing().record_extractor_version("extractor-v1")
    with pytest.raises(DocumentTransitionError, match="already been recorded"):
        processing.record_extractor_version("extractor-v2")


@pytest.mark.parametrize("value", [None, 1, True, "", " ", "v" * 129])
def test_versions_are_nonblank_bounded_strings(value: object) -> None:
    with pytest.raises(DocumentDomainError):
        _document().start_processing(
            at=STARTED_AT,
            processing_version=cast(str, value),
        )
    with pytest.raises(DocumentDomainError):
        _processing().record_extractor_version(cast(str, value))


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("", "Safe"),
        ("lowercase", "Safe"),
        ("INVALID-CODE", "Safe"),
        ("A" * 65, "Safe"),
        ("PROCESSING_FAILED", ""),
        ("PROCESSING_FAILED", "M" * 513),
        (1, "Safe"),
        ("PROCESSING_FAILED", 1),
    ],
)
def test_failure_metadata_is_strict_and_bounded(code: object, message: object) -> None:
    with pytest.raises(DocumentDomainError):
        DocumentFailure(cast(str, code), cast(str, message))


@pytest.mark.parametrize(
    "changes",
    [
        {"status": DocumentStatus.PROCESSING},
        {"processing_version": "v1"},
        {"extractor_version": "v1"},
        {"failure": DocumentFailure("PROCESSING_FAILED", "Failed safely.")},
    ],
)
def test_snapshot_status_and_metadata_must_be_consistent(
    changes: dict[str, object],
) -> None:
    with pytest.raises(DocumentDomainError, match="lifecycle metadata"):
        replace(_document(), **changes)


def test_timestamps_must_be_aware_and_chronological() -> None:
    with pytest.raises(DocumentDomainError, match="timezone-aware"):
        replace(_document(), created_at=CREATED_AT.replace(tzinfo=None))
    with pytest.raises(DocumentDomainError, match="start before creation"):
        _document().start_processing(
            at=CREATED_AT - timedelta(seconds=1),
            processing_version="v1",
        )
    with pytest.raises(DocumentDomainError, match="complete before it starts"):
        _processing().complete(at=CREATED_AT)
    with pytest.raises(DocumentDomainError, match="fail before it starts"):
        _processing().fail(
            at=CREATED_AT,
            code="PROCESSING_FAILED",
            safe_message="Failed.",
        )
