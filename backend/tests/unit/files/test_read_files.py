from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexus.authorization import PermissionCheckError
from nexus.errors import ErrorCode, NexusError
from nexus.files.application import FilePageCursor, GetFile, ListFiles
from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import FilePersistenceError

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FakePermissionChecker:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.error: Exception | None = None
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        self.calls.append((organization_public_id, user_public_id, permission_key))
        if self.error is not None:
            raise self.error
        return self.allowed


class FakePersistence:
    def __init__(self, files: tuple[File, ...] = ()) -> None:
        self.files = files
        self.file: File | None = files[0] if files else None
        self.error: Exception | None = None
        self.list_calls: list[dict[str, object]] = []
        self.get_calls: list[tuple[UUID, UUID]] = []

    async def list_files(
        self,
        *,
        organization_public_id: UUID,
        before_created_at: datetime | None,
        before_public_id: UUID | None,
        limit: int,
    ) -> tuple[File, ...]:
        self.list_calls.append(
            {
                "organization_public_id": organization_public_id,
                "before_created_at": before_created_at,
                "before_public_id": before_public_id,
                "limit": limit,
            }
        )
        if self.error is not None:
            raise self.error
        return self.files

    async def get_file(
        self,
        *,
        organization_public_id: UUID,
        file_public_id: UUID,
    ) -> File | None:
        self.get_calls.append((organization_public_id, file_public_id))
        if self.error is not None:
            raise self.error
        return self.file


def _file(*, created_at: datetime = NOW, public_id: UUID | None = None) -> File:
    return File(
        public_id=public_id or uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=42,
        storage_key=f"files/{uuid4().hex}",
        storage_status=FileStorageStatus.AVAILABLE,
        checksum_sha256=None,
        created_at=created_at,
        updated_at=created_at,
    )


def test_list_files_authorizes_and_fetches_limit_plus_one() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    files = (_file(), _file(), _file())
    persistence = FakePersistence(files)
    permissions = FakePermissionChecker()
    service = ListFiles(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=permissions,  # type: ignore[arg-type]
    )

    page = asyncio.run(
        service.execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
            limit=2,
        )
    )

    assert page.items == files[:2]
    assert page.next_cursor == FilePageCursor(
        created_at=files[1].created_at,
        public_id=files[1].public_id,
    )
    assert persistence.list_calls == [
        {
            "organization_public_id": organization_id,
            "before_created_at": None,
            "before_public_id": None,
            "limit": 3,
        }
    ]
    assert permissions.calls == [(organization_id, user_id, "files.read")]


def test_list_files_passes_complete_keyset_cursor() -> None:
    cursor = FilePageCursor(created_at=NOW, public_id=uuid4())
    persistence = FakePersistence(())
    service = ListFiles(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
    )

    page = asyncio.run(
        service.execute(
            organization_public_id=uuid4(),
            user_public_id=uuid4(),
            limit=50,
            cursor=cursor,
        )
    )

    assert page.items == ()
    assert page.next_cursor is None
    assert persistence.list_calls[0]["before_created_at"] == cursor.created_at
    assert persistence.list_calls[0]["before_public_id"] == cursor.public_id


@pytest.mark.parametrize("limit", [0, 101])
def test_list_files_rejects_unbounded_page_sizes(limit: int) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            ListFiles(
                persistence=FakePersistence(),  # type: ignore[arg-type]
                permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
            ).execute(
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
                limit=limit,
            )
        )


def test_file_read_permission_denial_does_not_query_files() -> None:
    persistence = FakePersistence()
    service = ListFiles(
        persistence=persistence,  # type: ignore[arg-type]
        permission_checker=FakePermissionChecker(allowed=False),  # type: ignore[arg-type]
    )

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            service.execute(
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
            )
        )

    assert captured.value.code is ErrorCode.FORBIDDEN
    assert persistence.list_calls == []


def test_file_read_permission_dependency_failure_is_service_unavailable() -> None:
    permissions = FakePermissionChecker()
    permissions.error = PermissionCheckError("database unavailable")

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            ListFiles(
                persistence=FakePersistence(),  # type: ignore[arg-type]
                permission_checker=permissions,  # type: ignore[arg-type]
            ).execute(
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
            )
        )

    assert captured.value.code is ErrorCode.SERVICE_UNAVAILABLE


def test_get_file_returns_authorized_tenant_scoped_file() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    file = _file()
    persistence = FakePersistence((file,))
    permissions = FakePermissionChecker()

    result = asyncio.run(
        GetFile(
            persistence=persistence,  # type: ignore[arg-type]
            permission_checker=permissions,  # type: ignore[arg-type]
        ).execute(
            organization_public_id=organization_id,
            user_public_id=user_id,
            file_public_id=file.public_id,
        )
    )

    assert result is file
    assert persistence.get_calls == [(organization_id, file.public_id)]
    assert permissions.calls == [(organization_id, user_id, "files.read")]


def test_get_file_returns_not_found_without_cross_tenant_disclosure() -> None:
    persistence = FakePersistence()
    persistence.file = None

    with pytest.raises(NexusError) as captured:
        asyncio.run(
            GetFile(
                persistence=persistence,  # type: ignore[arg-type]
                permission_checker=FakePermissionChecker(),  # type: ignore[arg-type]
            ).execute(
                organization_public_id=uuid4(),
                user_public_id=uuid4(),
                file_public_id=uuid4(),
            )
        )

    assert captured.value.code is ErrorCode.NOT_FOUND


@pytest.mark.parametrize("operation", ["list", "get"])
def test_file_read_persistence_failure_is_service_unavailable(operation: str) -> None:
    persistence = FakePersistence()
    persistence.error = FilePersistenceError("database unavailable")
    permissions = FakePermissionChecker()

    with pytest.raises(NexusError) as captured:
        if operation == "list":
            asyncio.run(
                ListFiles(
                    persistence=persistence,  # type: ignore[arg-type]
                    permission_checker=permissions,  # type: ignore[arg-type]
                ).execute(
                    organization_public_id=uuid4(),
                    user_public_id=uuid4(),
                )
            )
        else:
            asyncio.run(
                GetFile(
                    persistence=persistence,  # type: ignore[arg-type]
                    permission_checker=permissions,  # type: ignore[arg-type]
                ).execute(
                    organization_public_id=uuid4(),
                    user_public_id=uuid4(),
                    file_public_id=uuid4(),
                )
            )

    assert captured.value.code is ErrorCode.SERVICE_UNAVAILABLE
