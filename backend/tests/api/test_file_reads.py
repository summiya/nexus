from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.security import get_current_auth_context
from nexus.authentication.tokens import AuthTokenContext
from nexus.config.settings import Settings
from nexus.errors import ErrorCode, NexusError
from nexus.files.api.dependencies import (
    get_delete_file,
    get_file,
    get_issue_file_download,
    get_list_files,
)
from nexus.files.api.pagination import decode_file_cursor
from nexus.files.application import FilePage, FilePageCursor
from nexus.files.domain import File, FileStorageStatus
from nexus.files.ports import DownloadGrant, ObjectStorage
from nexus.main import create_app

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FakeListFilesService:
    def __init__(self, page: FilePage) -> None:
        self.page = page
        self.error: NexusError | None = None
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        limit: int,
        cursor: FilePageCursor | None,
    ) -> FilePage:
        self.calls.append(
            {
                "organization_public_id": organization_public_id,
                "user_public_id": user_public_id,
                "limit": limit,
                "cursor": cursor,
            }
        )
        if self.error is not None:
            raise self.error
        return self.page


class FakeGetFileService:
    def __init__(self, file: File) -> None:
        self.file = file
        self.error: NexusError | None = None
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> File:
        self.calls.append((organization_public_id, user_public_id, file_public_id))
        if self.error is not None:
            raise self.error
        return self.file


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key="bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE",
    )


def _file(
    *,
    status: FileStorageStatus = FileStorageStatus.AVAILABLE,
    created_at: datetime = NOW,
) -> File:
    return File(
        public_id=uuid4(),
        organization_public_id=uuid4(),
        created_by_user_public_id=uuid4(),
        original_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=42,
        storage_key=f"files/{uuid4().hex}",
        storage_status=status,
        checksum_sha256="a" * 64,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=1),
    )


def _app() -> tuple[FastAPI, UUID, UUID]:
    organization_id = uuid4()
    user_id = uuid4()
    app = create_app(_settings(), object_storage=Mock(spec=ObjectStorage))
    app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
        user_public_id=user_id,
        organization_public_id=organization_id,
        session_public_id=uuid4(),
    )
    return app, organization_id, user_id


def test_list_files_returns_safe_metadata_and_opaque_next_cursor() -> None:
    first = _file()
    second = _file(created_at=NOW - timedelta(seconds=1))
    next_position = FilePageCursor(
        created_at=second.created_at,
        public_id=second.public_id,
    )
    service = FakeListFilesService(
        FilePage(items=(first, second), next_cursor=next_position)
    )
    app, organization_id, user_id = _app()
    app.dependency_overrides[get_list_files] = lambda: service

    with TestClient(app) as client:
        response = client.get("/api/v1/files?limit=2")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert service.calls == [
        {
            "organization_public_id": organization_id,
            "user_public_id": user_id,
            "limit": 2,
            "cursor": None,
        }
    ]
    body = response.json()
    assert [item["public_id"] for item in body["items"]] == [
        str(first.public_id),
        str(second.public_id),
    ]
    assert decode_file_cursor(body["next_cursor"]) == next_position
    serialized = response.text
    for forbidden in (
        "organization_public_id",
        "created_by_user_public_id",
        "storage_key",
        "checksum_sha256",
        "azure",
        "blob_url",
    ):
        assert forbidden not in serialized


def test_list_files_accepts_returned_cursor() -> None:
    cursor = FilePageCursor(created_at=NOW, public_id=uuid4())
    service = FakeListFilesService(FilePage(items=(), next_cursor=None))
    app, _, _ = _app()
    app.dependency_overrides[get_list_files] = lambda: service

    from nexus.files.api.pagination import encode_file_cursor

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/files",
            params={"cursor": encode_file_cursor(cursor), "limit": 25},
        )

    assert response.status_code == 200
    assert service.calls[0]["cursor"] == cursor
    assert service.calls[0]["limit"] == 25


def test_list_files_rejects_malformed_cursor_before_service_call() -> None:
    service = FakeListFilesService(FilePage(items=(), next_cursor=None))
    app, _, _ = _app()
    app.dependency_overrides[get_list_files] = lambda: service

    with TestClient(app) as client:
        response = client.get("/api/v1/files?cursor=not-a-valid-cursor")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert service.calls == []


def test_list_files_enforces_bounded_page_size() -> None:
    service = FakeListFilesService(FilePage(items=(), next_cursor=None))
    app, _, _ = _app()
    app.dependency_overrides[get_list_files] = lambda: service

    with TestClient(app) as client:
        response = client.get("/api/v1/files?limit=101")

    assert response.status_code == 422
    assert service.calls == []


def test_get_file_returns_safe_metadata_for_all_lifecycle_statuses() -> None:
    file = _file(status=FileStorageStatus.FAILED)
    service = FakeGetFileService(file)
    app, organization_id, user_id = _app()
    app.dependency_overrides[get_file] = lambda: service

    with TestClient(app) as client:
        response = client.get(f"/api/v1/files/{file.public_id}")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert service.calls == [(organization_id, user_id, file.public_id)]
    assert response.json() == {
        "public_id": str(file.public_id),
        "original_name": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 42,
        "storage_status": "failed",
        "created_at": "2026-09-26T12:00:00Z",
        "updated_at": "2026-09-26T12:00:01Z",
    }
    assert "storage_key" not in response.text
    assert "checksum_sha256" not in response.text


def test_get_file_preserves_safe_not_found_response() -> None:
    file = _file()
    service = FakeGetFileService(file)
    service.error = NexusError(
        ErrorCode.NOT_FOUND,
        "The requested resource was not found.",
    )
    app, _, _ = _app()
    app.dependency_overrides[get_file] = lambda: service

    with TestClient(app) as client:
        response = client.get(f"/api/v1/files/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_file_read_endpoints_require_authentication() -> None:
    app = create_app(_settings(), object_storage=Mock(spec=ObjectStorage))

    with TestClient(app) as client:
        list_response = client.get("/api/v1/files")
        get_response = client.get(f"/api/v1/files/{uuid4()}")
        delete_response = client.delete(f"/api/v1/files/{uuid4()}")

    assert list_response.status_code == 401
    assert get_response.status_code == 401
    assert delete_response.status_code == 401


def test_openapi_exposes_only_metadata_read_endpoints() -> None:
    app, _, _ = _app()

    schema = app.openapi()
    list_operation = schema["paths"]["/api/v1/files"]["get"]
    file_path = schema["paths"]["/api/v1/files/{file_public_id}"]
    get_operation = file_path["get"]
    delete_operation = file_path["delete"]

    assert list_operation["security"] == [{"HTTPBearer": []}]
    assert get_operation["security"] == [{"HTTPBearer": []}]
    assert delete_operation["security"] == [{"HTTPBearer": []}]
    assert "204" in delete_operation["responses"]
    assert "200" in list_operation["responses"]
    assert "422" in list_operation["responses"]
    schemas = schema["components"]["schemas"]
    file_schema = schemas["FileMetadataResponseBody"]["properties"]
    assert set(file_schema) == {
        "public_id",
        "original_name",
        "mime_type",
        "size_bytes",
        "storage_status",
        "created_at",
        "updated_at",
    }
    status_schema = schemas["FileMetadataStorageStatus"]
    assert status_schema["enum"] == ["pending", "available", "failed"]



class FakeDeleteFileService:
    def __init__(self) -> None:
        self.error: NexusError | None = None
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> None:
        self.calls.append((organization_public_id, user_public_id, file_public_id))
        if self.error is not None:
            raise self.error


def test_delete_endpoint_returns_204_and_no_body() -> None:
    service = FakeDeleteFileService()
    app, organization_id, user_id = _app()
    file_public_id = uuid4()
    app.dependency_overrides[get_delete_file] = lambda: service

    with TestClient(app) as client:
        response = client.delete(f"/api/v1/files/{file_public_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [(organization_id, user_id, file_public_id)]


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (ErrorCode.NOT_FOUND, 404),
        (ErrorCode.FORBIDDEN, 403),
        (ErrorCode.SERVICE_UNAVAILABLE, 503),
    ],
)
def test_delete_endpoint_preserves_safe_errors(
    code: ErrorCode,
    status_code: int,
) -> None:
    service = FakeDeleteFileService()
    service.error = NexusError(
        code,
        "safe",
        retryable=code is ErrorCode.SERVICE_UNAVAILABLE,
    )
    app, _, _ = _app()
    app.dependency_overrides[get_delete_file] = lambda: service

    with TestClient(app) as client:
        response = client.delete(f"/api/v1/files/{uuid4()}")

    assert response.status_code == status_code
    assert "storage_key" not in response.text
    assert "azure" not in response.text.lower()



class FakeIssueFileDownloadService:
    def __init__(self) -> None:
        self.error: NexusError | None = None
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        file_public_id: UUID,
    ) -> DownloadGrant:
        self.calls.append(
            (organization_public_id, user_public_id, file_public_id)
        )
        if self.error is not None:
            raise self.error
        return DownloadGrant(
            url="https://storage.example/file?sig=SENSITIVE",
            expires_at=NOW + timedelta(minutes=5),
        )


def test_download_endpoint_returns_ephemeral_grant_with_no_store() -> None:
    service = FakeIssueFileDownloadService()
    app, organization_id, user_id = _app()
    file_public_id = uuid4()
    app.dependency_overrides[get_issue_file_download] = lambda: service

    with TestClient(app) as client:
        response = client.post(f"/api/v1/files/{file_public_id}/download")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == {
        "url": "https://storage.example/file?sig=SENSITIVE",
        "expires_at": "2026-09-26T12:05:00Z",
    }
    assert service.calls == [(organization_id, user_id, file_public_id)]


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (ErrorCode.NOT_FOUND, 404),
        (ErrorCode.FORBIDDEN, 403),
        (ErrorCode.CONFLICT, 409),
    ],
)
def test_download_endpoint_preserves_safe_authorization_and_state_errors(
    code: ErrorCode,
    status_code: int,
) -> None:
    service = FakeIssueFileDownloadService()
    service.error = NexusError(code, "safe")
    app, _, _ = _app()
    app.dependency_overrides[get_issue_file_download] = lambda: service

    with TestClient(app) as client:
        response = client.post(f"/api/v1/files/{uuid4()}/download")

    assert response.status_code == status_code
    assert "storage_key" not in response.text
    assert "sig=" not in response.text
