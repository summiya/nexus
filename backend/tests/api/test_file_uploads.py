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
from nexus.files.api.dependencies import get_initiate_file_upload
from nexus.files.application import InitiatedFileUpload
from nexus.files.ports import ObjectStorage, UploadGrant
from nexus.main import create_app

CREATED_AT = datetime(2026, 9, 25, 12, tzinfo=UTC)
EXPIRES_AT = CREATED_AT + timedelta(minutes=10)
SIGNED_URL = (
    "https://account.blob.example/container/files/key"
    "?sv=version&sig=sensitive%2Bvalue&sp=c"
)


class FakeInitiateFileUploadService:
    def __init__(self, result: InitiatedFileUpload) -> None:
        self.result = result
        self.error: NexusError | None = None
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        original_name: str,
        mime_type: str | None,
        declared_size_bytes: int,
    ) -> InitiatedFileUpload:
        self.calls.append(
            {
                "organization_public_id": organization_public_id,
                "user_public_id": user_public_id,
                "original_name": original_name,
                "mime_type": mime_type,
                "declared_size_bytes": declared_size_bytes,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["https://nexus.example"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        file_upload_context_key=("bmV4dXMtZGV2ZWxvcG1lbnQtdXBsb2FkLWtleS0wMDE"),
    )


def _result() -> InitiatedFileUpload:
    return InitiatedFileUpload(
        grant=UploadGrant(
            url=SIGNED_URL,
            method="PUT",
            headers={
                "x-ms-blob-type": "BlockBlob",
                "X-Signed-Header": " value-preserved ",
            },
            expires_at=EXPIRES_AT,
        ),
        protected_context="nuc1.primary.opaque-context",
    )


def _app(
    service: FakeInitiateFileUploadService,
    *,
    authenticated: bool = True,
) -> tuple[FastAPI, UUID, UUID]:
    organization_public_id = uuid4()
    user_public_id = uuid4()
    app = create_app(
        _settings(),
        object_storage=Mock(spec=ObjectStorage),
    )
    app.dependency_overrides[get_initiate_file_upload] = lambda: service
    if authenticated:
        app.dependency_overrides[get_current_auth_context] = lambda: AuthTokenContext(
            user_public_id=user_public_id,
            organization_public_id=organization_public_id,
            session_public_id=uuid4(),
        )
    return app, organization_public_id, user_public_id


def test_upload_initiation_uses_trusted_scope_and_returns_exact_safe_response() -> None:
    result = _result()
    service = FakeInitiateFileUploadService(result)
    app, organization_public_id, user_public_id = _app(service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/uploads",
            json={
                "original_name": "  report.pdf  ",
                "mime_type": " APPLICATION/PDF ",
                "size_bytes": 42,
            },
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert service.calls == [
        {
            "organization_public_id": organization_public_id,
            "user_public_id": user_public_id,
            "original_name": "  report.pdf  ",
            "mime_type": " APPLICATION/PDF ",
            "declared_size_bytes": 42,
        }
    ]
    assert response.json() == {
        "upload": {
            "url": SIGNED_URL,
            "method": "PUT",
            "headers": {
                "x-ms-blob-type": "BlockBlob",
                "X-Signed-Header": " value-preserved ",
            },
            "metadata": {
                "nexus_upload_context": "nuc1.primary.opaque-context",
            },
            "expires_at": "2026-09-25T12:10:00Z",
        },
    }


def test_upload_response_exposes_no_internal_file_or_provider_fields() -> None:
    service = FakeInitiateFileUploadService(_result())
    app, _, _ = _app(service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/uploads",
            json={"original_name": "file.txt", "mime_type": None, "size_bytes": 0},
        )

    body = response.json()
    assert set(body) == {"upload"}
    assert set(body["upload"]) == {
        "url",
        "method",
        "headers",
        "metadata",
        "expires_at",
    }
    assert set(body["upload"]["metadata"]) == {"nexus_upload_context"}
    serialized = response.text
    assert "organization_public_id" not in serialized
    assert "created_by_user_public_id" not in serialized
    assert "storage_key" not in serialized


def test_upload_initiation_requires_authentication() -> None:
    service = FakeInitiateFileUploadService(_result())
    app, _, _ = _app(service, authenticated=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/uploads",
            json={"original_name": "file.txt", "size_bytes": 1},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            NexusError(
                ErrorCode.FORBIDDEN,
                "You are not allowed to perform this action.",
            ),
            403,
            "FORBIDDEN",
        ),
        (
            NexusError(ErrorCode.VALIDATION_ERROR, "File name is invalid."),
            422,
            "VALIDATION_ERROR",
        ),
        (
            NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The file upload could not be initiated.",
                retryable=True,
            ),
            503,
            "SERVICE_UNAVAILABLE",
        ),
    ],
)
def test_upload_initiation_uses_existing_safe_error_envelopes(
    error: NexusError,
    expected_status: int,
    expected_code: str,
) -> None:
    service = FakeInitiateFileUploadService(_result())
    service.error = error
    app, _, _ = _app(service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/uploads",
            json={"original_name": "file.txt", "size_bytes": 1},
        )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


@pytest.mark.parametrize(
    "body",
    [
        {"original_name": "file.txt", "size_bytes": True},
        {"original_name": "file.txt", "size_bytes": "1"},
        {"original_name": "file.txt", "size_bytes": 1.5},
        {"original_name": "file.txt", "size_bytes": -1},
        {"original_name": "x" * 256, "size_bytes": 1},
        {"original_name": "file.txt", "mime_type": "x" * 256, "size_bytes": 1},
        {"original_name": "file.txt", "size_bytes": 1, "storage_key": "chosen"},
        {
            "original_name": "file.txt",
            "size_bytes": 1,
            "organization_public_id": str(uuid4()),
        },
        {"size_bytes": 1},
    ],
)
def test_upload_request_rejects_invalid_or_extra_fields(
    body: dict[str, object],
) -> None:
    service = FakeInitiateFileUploadService(_result())
    app, _, _ = _app(service)

    with TestClient(app) as client:
        response = client.post("/api/v1/files/uploads", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert service.calls == []


def test_upload_request_rejects_malformed_json() -> None:
    service = FakeInitiateFileUploadService(_result())
    app, _, _ = _app(service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/uploads",
            content=b"{",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    assert service.calls == []


def test_openapi_describes_provider_neutral_authenticated_upload_initiation() -> None:
    app, _, _ = _app(FakeInitiateFileUploadService(_result()))

    schema = app.openapi()
    operation = schema["paths"]["/api/v1/files/uploads"]["post"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert "application/json" in operation["requestBody"]["content"]
    assert "200" in operation["responses"]
    assert "422" in operation["responses"]
    schema_names = schema["components"]["schemas"]
    assert not any(
        provider_name in name.lower()
        for name in schema_names
        for provider_name in ("azure", "blob", "sas")
    )
