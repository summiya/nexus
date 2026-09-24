from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.dependencies import get_session_service
from nexus.authentication.session_service import SessionTokenResult
from nexus.errors import ErrorCode, NexusError


class FakeSessionService:
    def __init__(self, *, error: NexusError | None = None) -> None:
        self.error = error
        self.refresh_tokens: list[str] = []

    async def refresh_session(self, *, refresh_token: str) -> SessionTokenResult:
        self.refresh_tokens.append(refresh_token)
        if self.error is not None:
            raise self.error
        return SessionTokenResult(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            token_type="bearer",
            expires_in=900,
        )


@contextmanager
def override_session_service(
    app: FastAPI,
    service: FakeSessionService,
) -> Iterator[None]:
    app.dependency_overrides[get_session_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session_service, None)


def test_refresh_endpoint_returns_only_rotated_session_tokens_without_access_token(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeSessionService()

    with override_session_service(app, service):
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "old-refresh-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "token_type": "bearer",
        "expires_in": 900,
    }
    assert service.refresh_tokens == ["old-refresh-token"]


def test_refresh_endpoint_rejects_unrelated_fields(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeSessionService()

    with override_session_service(app, service):
        response = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "refresh-token",
                "organization_public_id": "client-controlled",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert service.refresh_tokens == []


def test_refresh_endpoint_returns_generic_unauthorized_error(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeSessionService(
        error=NexusError(
            ErrorCode.UNAUTHORIZED,
            "Authentication credentials are invalid.",
        )
    )

    with override_session_service(app, service):
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid-refresh-token"},
        )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": ErrorCode.UNAUTHORIZED,
        "message": "Authentication credentials are invalid.",
        "request_id": response.headers["X-Request-ID"],
    }
    assert service.refresh_tokens == ["invalid-refresh-token"]
