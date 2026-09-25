from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.files.domain import File, FileStorageStatus, FileUploadAttempt

TIMESTAMP = datetime(2026, 9, 24, tzinfo=UTC)


def _file(**changes: object) -> File:
    file = File(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=None,
        storage_key="opaque-file-key",
        storage_status=FileStorageStatus.PENDING,
        checksum_sha256=None,
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    return replace(file, **changes)


def _upload_attempt(**changes: object) -> FileUploadAttempt:
    attempt = FileUploadAttempt(
        file_public_id=uuid4(),
        organization_public_id=uuid4(),
        declared_size_bytes=42,
        grant_expires_at=TIMESTAMP + timedelta(minutes=15),
        created_at=TIMESTAMP,
    )
    return replace(attempt, **changes)


def test_storage_status_values_are_stable_lowercase_contracts() -> None:
    assert [status.value for status in FileStorageStatus] == [
        "pending",
        "available",
        "failed",
    ]


def test_pending_file_allows_unknown_size_and_missing_checksum() -> None:
    file = _file()

    assert file.size_bytes is None
    assert file.checksum_sha256 is None


def test_available_file_requires_size_but_checksum_remains_optional() -> None:
    file = _file(
        storage_status=FileStorageStatus.AVAILABLE,
        size_bytes=42,
    )

    assert file.storage_status is FileStorageStatus.AVAILABLE
    assert file.size_bytes == 42
    assert file.checksum_sha256 is None


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("original_name", " "),
        ("mime_type", ""),
        ("storage_key", "\t"),
        ("original_name", "a" * 256),
        ("mime_type", "a" * 256),
        ("storage_key", "a" * 1025),
    ],
)
def test_file_rejects_invalid_bounded_metadata(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError):
        _file(**{field_name: value})


def test_file_rejects_negative_size() -> None:
    with pytest.raises(ValueError, match="size_bytes must not be negative"):
        _file(size_bytes=-1)


def test_available_file_rejects_missing_size() -> None:
    with pytest.raises(ValueError, match="available File must have a size"):
        _file(storage_status=FileStorageStatus.AVAILABLE)


@pytest.mark.parametrize(
    "checksum",
    [
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        "sha256:" + "a" * 64,
    ],
)
def test_file_rejects_invalid_optional_checksum(checksum: str) -> None:
    with pytest.raises(
        ValueError,
        match="checksum_sha256 must be 64 lowercase hexadecimal characters",
    ):
        _file(checksum_sha256=checksum)


def test_file_accepts_valid_optional_checksum() -> None:
    assert _file(checksum_sha256="a" * 64).checksum_sha256 == "a" * 64


@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
def test_file_requires_timezone_aware_timestamps(field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be timezone-aware"):
        _file(**{field_name: TIMESTAMP.replace(tzinfo=None)})


def test_upload_attempt_preserves_trusted_upload_metadata() -> None:
    attempt = _upload_attempt(declared_size_bytes=0)

    assert attempt.declared_size_bytes == 0
    assert attempt.grant_expires_at == TIMESTAMP + timedelta(minutes=15)
    assert attempt.created_at == TIMESTAMP


@pytest.mark.parametrize("declared_size_bytes", [True, False, 1.0, "1", None])
def test_upload_attempt_requires_integer_declared_size(
    declared_size_bytes: object,
) -> None:
    with pytest.raises(
        TypeError,
        match="declared_size_bytes must be an integer",
    ):
        _upload_attempt(declared_size_bytes=declared_size_bytes)


def test_upload_attempt_rejects_negative_declared_size() -> None:
    with pytest.raises(
        ValueError,
        match="declared_size_bytes must not be negative",
    ):
        _upload_attempt(declared_size_bytes=-1)


@pytest.mark.parametrize("field_name", ["grant_expires_at", "created_at"])
def test_upload_attempt_requires_timezone_aware_timestamps(field_name: str) -> None:
    value = getattr(_upload_attempt(), field_name)

    with pytest.raises(ValueError, match=f"{field_name} must be timezone-aware"):
        _upload_attempt(**{field_name: value.replace(tzinfo=None)})


@pytest.mark.parametrize(
    "grant_expires_at",
    [TIMESTAMP, TIMESTAMP - timedelta(microseconds=1)],
)
def test_upload_attempt_requires_expiration_after_creation(
    grant_expires_at: datetime,
) -> None:
    with pytest.raises(
        ValueError,
        match="grant_expires_at must be later than created_at",
    ):
        _upload_attempt(grant_expires_at=grant_expires_at)


def test_upload_attempt_is_immutable() -> None:
    attempt = _upload_attempt()

    with pytest.raises(FrozenInstanceError):
        attempt.declared_size_bytes = 100  # type: ignore[misc]
