from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.errors import ErrorCode, NexusError
from nexus.files.application import DeleteFile
from nexus.files.ports import (
    FileDeletionTarget,
    FilePersistenceError,
    ObjectStorageError,
)

NOW = datetime(2026, 9, 26, 16, tzinfo=UTC)
STORAGE_KEY = "files/0123456789abcdef0123456789abcdef"


class FakePermissionChecker:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        self.calls.append((organization_public_id, user_public_id, permission_key))
        return self.allowed


class FakePersistence:
    def __init__(self, events: list[str] | None = None) -> None:
        self.target: FileDeletionTarget | None = FileDeletionTarget(
            storage_key=STORAGE_KEY
        )
        self.prepare_error: Exception | None = None
        self.finalize_error: Exception | None = None
        self.events = events if events is not None else []

    async def prepare_file_deletion(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
        updated_at: datetime,
    ) -> FileDeletionTarget | None:
        del organization_public_id, file_public_id
        assert updated_at == NOW
        self.events.append("prepare")
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.target

    async def delete_file_record(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> None:
        del organization_public_id, file_public_id
        self.events.append("finalize")
        if self.finalize_error is not None:
            raise self.finalize_error


class FakeStorage:
    def __init__(self, events: list[str] | None = None) -> None:
        self.error: Exception | None = None
        self.events = events if events is not None else []

    async def delete_object(self, *, storage_key: str) -> None:
        assert storage_key == STORAGE_KEY
        self.events.append("storage")
        if self.error is not None:
            raise self.error


def _service(
    persistence: FakePersistence,
    storage: FakeStorage,
    permissions: FakePermissionChecker | None = None,
) -> DeleteFile:
    return DeleteFile(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permissions or FakePermissionChecker(),  # type: ignore[arg-type]
        object_storage=storage,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


def _ids() -> tuple[UUID, UUID, UUID]:
    return uuid4(), uuid4(), uuid4()


def test_blob_is_deleted_before_metadata_row() -> None:
    events: list[str] = []
    persistence = FakePersistence(events)
    storage = FakeStorage(events)
    organization_id, user_id, file_id = _ids()

    asyncio.run(
        _service(persistence, storage).execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
            file_public_id=file_id,
        )
    )

    assert events == ["prepare", "storage", "finalize"]


def test_storage_failure_leaves_deleting_and_retry_completes() -> None:
    persistence = FakePersistence()
    storage = FakeStorage()
    storage.error = ObjectStorageError("provider detail")
    organization_id, user_id, file_id = _ids()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _service(persistence, storage).execute(
                organization_public_id=organization_id,
                user_public_id=user_id,
                file_public_id=file_id,
            )
        )

    assert captured.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert persistence.events == ["prepare"]

    storage.error = None
    asyncio.run(
        _service(persistence, storage).execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
            file_public_id=file_id,
        )
    )
    assert persistence.events == ["prepare", "prepare", "finalize"]


def test_finalize_failure_is_retryable_after_blob_delete() -> None:
    persistence = FakePersistence()
    persistence.finalize_error = FilePersistenceError("database detail")
    storage = FakeStorage()
    organization_id, user_id, file_id = _ids()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _service(persistence, storage).execute(
                organization_public_id=organization_id,
                user_public_id=user_id,
                file_public_id=file_id,
            )
        )

    assert captured.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert storage.events == ["storage"]

    persistence.finalize_error = None
    asyncio.run(
        _service(persistence, storage).execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
            file_public_id=file_id,
        )
    )
    assert storage.events == ["storage", "storage"]


def test_missing_or_cross_tenant_file_is_not_found_without_storage_call() -> None:
    persistence = FakePersistence()
    persistence.target = None
    storage = FakeStorage()
    organization_id, user_id, file_id = _ids()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _service(persistence, storage).execute(
                organization_public_id=organization_id,
                user_public_id=user_id,
                file_public_id=file_id,
            )
        )

    assert captured.value.code is ErrorCode.NOT_FOUND
    assert storage.events == []


def test_missing_permission_is_forbidden_before_prepare() -> None:
    persistence = FakePersistence()
    storage = FakeStorage()
    permissions = FakePermissionChecker(allowed=False)
    organization_id, user_id, file_id = _ids()

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            _service(persistence, storage, permissions).execute(
                organization_public_id=organization_id,
                user_public_id=user_id,
                file_public_id=file_id,
            )
        )

    assert captured.value.code is ErrorCode.FORBIDDEN
    assert persistence.events == []
    assert storage.events == []
    assert permissions.calls == [(organization_id, user_id, "files.delete")]


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


def test_delete_logs_only_safe_hashed_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.files.application.delete_file as delete_module

    persistence = FakePersistence()
    storage = FakeStorage()
    logger = RecordingLogger()
    monkeypatch.setattr(delete_module, "logger", logger)
    organization_id, user_id, file_id = _ids()

    asyncio.run(
        _service(persistence, storage).execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
            file_public_id=file_id,
        )
    )

    serialized = repr(logger.events)
    assert "file_deleted" in serialized
    assert "correlation" in serialized
    assert STORAGE_KEY not in serialized
    assert str(organization_id) not in serialized
    assert str(file_id) not in serialized
