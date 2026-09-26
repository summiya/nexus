from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from nexus.files.application import VerifyUploadCompletion
from nexus.files.application import verify_upload_completion as completion_module
from nexus.files.domain import File, FileStorageStatus, UploadContext
from nexus.files.ports import (
    FileIdentityConflictError,
    FileReferenceError,
    ObjectStorageNotFoundError,
    StoredObjectProperties,
    UploadCompletionEvent,
    UploadCompletionRejectedError,
    UploadCompletionRejectionReason,
    UploadContextProtectionError,
)

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
STORAGE_KEY = "files/0123456789abcdef0123456789abcdef"


class FakeStorage:
    def __init__(self, properties: StoredObjectProperties) -> None:
        self.properties = properties
        self.error: Exception | None = None
        self.calls: list[str] = []

    async def get_object_properties(self, *, storage_key: str) -> StoredObjectProperties:
        self.calls.append(storage_key)
        if self.error is not None:
            raise self.error
        return self.properties


class FakeProtector:
    def __init__(self, context: UploadContext) -> None:
        self.context = context
        self.error: Exception | None = None
        self.calls: list[str] = []

    def unprotect(self, value: str) -> UploadContext:
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return self.context


class FakePersistence:
    def __init__(self) -> None:
        self.files: list[File] = []
        self.error: Exception | None = None

    async def register_completed_upload(self, file: File) -> None:
        if self.error is not None:
            raise self.error
        self.files.append(file)


def _context(**changes: object) -> UploadContext:
    context = UploadContext(
        version=1,
        file_public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        storage_key=STORAGE_KEY,
        original_name="report.pdf",
        mime_type="application/pdf",
        declared_size_bytes=42,
        issued_at=NOW - timedelta(minutes=5),
        grant_expires_at=NOW + timedelta(minutes=5),
    )
    return replace(context, **changes)


def _event(**changes: object) -> UploadCompletionEvent:
    event = UploadCompletionEvent(
        event_id="event-1",
        source="azure-primary",
        storage_key=STORAGE_KEY,
        occurred_at=NOW,
        entity_tag="0x8D123",
        reported_size_bytes=42,
    )
    return replace(event, **changes)


def _properties(**changes: object) -> StoredObjectProperties:
    values: dict[str, object] = {
        "entity_tag": "0x8D123",
        "size_bytes": 42,
        "metadata": {"nexus_upload_context": "protected-context"},
        **changes,
    }
    return StoredObjectProperties(**values)  # type: ignore[arg-type]


def _service(
    *,
    context: UploadContext | None = None,
    properties: StoredObjectProperties | None = None,
) -> tuple[VerifyUploadCompletion, FakeStorage, FakeProtector, FakePersistence]:
    storage = FakeStorage(properties or _properties())
    protector = FakeProtector(context or _context())
    persistence = FakePersistence()
    service = VerifyUploadCompletion(
        object_storage=storage,  # type: ignore[arg-type]
        context_protector=protector,
        persistence=persistence,  # type: ignore[arg-type]
        max_size_bytes=536_870_912,
        clock=lambda: NOW,
    )
    return service, storage, protector, persistence


def test_valid_completion_registers_pending_file_with_verified_actual_size() -> None:
    service, _storage, _protector, persistence = _service()

    asyncio.run(service.handle(_event()))

    assert len(persistence.files) == 1
    file = persistence.files[0]
    assert file.storage_status is FileStorageStatus.PENDING
    assert file.size_bytes == 42
    assert file.checksum_sha256 is None
    assert file.created_at == NOW


@pytest.mark.parametrize(
    ("storage_error", "property_changes", "log_event"),
    [
        (
            ObjectStorageNotFoundError("safe"),
            {},
            "file_upload_completion_blob_missing",
        ),
        (
            None,
            {"entity_tag": "0xNEWER"},
            "file_upload_completion_stale_entity_tag",
        ),
    ],
)
def test_missing_or_stale_blob_is_distinct_safe_noop(
    storage_error: Exception | None,
    property_changes: dict[str, object],
    log_event: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, storage, protector, persistence = _service(
        properties=_properties(**property_changes)
    )
    storage.error = storage_error
    safe_logger = Mock()
    monkeypatch.setattr(completion_module, "logger", safe_logger)

    asyncio.run(service.handle(_event()))

    assert protector.calls == []
    assert persistence.files == []
    safe_logger.info.assert_called_once()
    assert safe_logger.info.call_args.args == (log_event,)
    assert set(safe_logger.info.call_args.kwargs) == {"correlation"}
    assert STORAGE_KEY not in repr(safe_logger.info.call_args)


@pytest.mark.parametrize(
    ("context", "properties", "event", "expected_reason"),
    [
        (
            _context(),
            _properties(metadata={}),
            _event(),
            UploadCompletionRejectionReason.MISSING_UPLOAD_CONTEXT,
        ),
        (
            _context(storage_key="files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            _properties(),
            _event(),
            UploadCompletionRejectionReason.STORAGE_KEY_MISMATCH,
        ),
        (
            _context(declared_size_bytes=41),
            _properties(),
            _event(),
            UploadCompletionRejectionReason.SIZE_MISMATCH,
        ),
        (
            _context(),
            _properties(),
            _event(reported_size_bytes=41),
            UploadCompletionRejectionReason.SIZE_MISMATCH,
        ),
        (
            _context(declared_size_bytes=536_870_913),
            _properties(size_bytes=536_870_913),
            _event(reported_size_bytes=536_870_913),
            UploadCompletionRejectionReason.SIZE_LIMIT_EXCEEDED,
        ),
    ],
)
def test_invalid_completion_is_permanently_rejected_before_persistence(
    context: UploadContext,
    properties: StoredObjectProperties,
    event: UploadCompletionEvent,
    expected_reason: UploadCompletionRejectionReason,
) -> None:
    service, _storage, _protector, persistence = _service(
        context=context,
        properties=properties,
    )

    with pytest.raises(UploadCompletionRejectedError) as captured:
        asyncio.run(service.handle(event))

    assert captured.value.reason is expected_reason
    assert persistence.files == []


def test_invalid_protected_context_is_permanently_rejected() -> None:
    service, _storage, protector, persistence = _service()
    protector.error = UploadContextProtectionError(
        "File upload context protection failed"
    )

    with pytest.raises(UploadCompletionRejectedError) as captured:
        asyncio.run(service.handle(_event()))

    assert (
        captured.value.reason
        is UploadCompletionRejectionReason.INVALID_UPLOAD_CONTEXT
    )
    assert persistence.files == []


@pytest.mark.parametrize(
    ("persistence_error", "expected_reason"),
    [
        (
            FileReferenceError("invalid reference"),
            UploadCompletionRejectionReason.INVALID_OWNER,
        ),
        (
            FileIdentityConflictError("identity conflict"),
            UploadCompletionRejectionReason.FILE_IDENTITY_CONFLICT,
        ),
    ],
)
def test_permanent_persistence_anomaly_is_safely_classified(
    persistence_error: Exception,
    expected_reason: UploadCompletionRejectionReason,
) -> None:
    service, _storage, _protector, persistence = _service()
    persistence.error = persistence_error

    with pytest.raises(UploadCompletionRejectedError) as captured:
        asyncio.run(service.handle(_event()))

    assert captured.value.reason is expected_reason
