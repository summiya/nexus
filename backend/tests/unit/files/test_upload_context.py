from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.files.domain import UPLOAD_CONTEXT_VERSION, UploadContext

ISSUED_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _context(**changes: object) -> UploadContext:
    context = UploadContext(
        version=UPLOAD_CONTEXT_VERSION,
        file_public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        storage_key=f"files/{uuid4().hex}",
        original_name="report.pdf",
        mime_type="application/pdf",
        declared_size_bytes=42,
        issued_at=ISSUED_AT,
        grant_expires_at=ISSUED_AT + timedelta(minutes=10),
    )
    return replace(context, **changes)


def test_upload_context_preserves_trusted_provider_neutral_values() -> None:
    context = _context(declared_size_bytes=0)

    assert context.version == 1
    assert context.declared_size_bytes == 0
    assert context.storage_key.startswith("files/")
    assert "report.pdf" not in repr(context)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_upload_context_requires_integer_declared_size(value: object) -> None:
    with pytest.raises(TypeError, match="declared_size_bytes must be an integer"):
        _context(declared_size_bytes=value)


def test_upload_context_rejects_negative_declared_size() -> None:
    with pytest.raises(ValueError, match="declared_size_bytes must not be negative"):
        _context(declared_size_bytes=-1)


@pytest.mark.parametrize("field_name", ["issued_at", "grant_expires_at"])
def test_upload_context_requires_timezone_aware_timestamps(field_name: str) -> None:
    value = getattr(_context(), field_name)

    with pytest.raises(ValueError, match=f"{field_name} must be timezone-aware"):
        _context(**{field_name: value.replace(tzinfo=None)})


def test_upload_context_requires_expiration_after_issue() -> None:
    with pytest.raises(
        ValueError,
        match="grant_expires_at must be later than issued_at",
    ):
        _context(grant_expires_at=ISSUED_AT)


@pytest.mark.parametrize("version", [0, 2, True, 1.0, "1"])
def test_upload_context_rejects_unknown_version(version: object) -> None:
    with pytest.raises(ValueError, match="version is unsupported"):
        _context(version=version)


def test_upload_context_is_immutable() -> None:
    context = _context()

    with pytest.raises(FrozenInstanceError):
        context.declared_size_bytes = 100  # type: ignore[misc]
