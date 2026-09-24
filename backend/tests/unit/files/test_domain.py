from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.files.domain import File, FileStorageStatus

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
