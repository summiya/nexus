from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.dependencies import get_login_service
from nexus.authentication.login_service import LoginOtpRequest
from nexus.errors import ErrorCode, NexusError


class FakeLoginService:
    def __init__(self, *, error: NexusError | None = None) -> None:
        self.error = error
        self.requests: list[LoginOtpRequest] = []

    def request_login_otp(self, *, request: LoginOtpRequest) -> None:
        self.requests.append(request)
        if self.error is not None:
            raise self.error


@contextmanager
def override_login_service(
    app: FastAPI,
    service: FakeLoginService,
) -> Iterator[None]:
    app.dependency_overrides[get_login_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_login_service, None)


@pytest.mark.parametrize(
    "email",
    ["registered@example.com", "unknown@example.com"],
)
def test_login_endpoint_returns_generic_accepted_response(
    app: FastAPI,
    client: TestClient,
    email: str,
) -> None:
    service = FakeLoginService()

    with override_login_service(app, service):
        response = client.post("/api/v1/auth/login", json={"email": email})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert service.requests == [LoginOtpRequest(email=email)]


def test_login_endpoint_rejects_client_supplied_purpose(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeLoginService()

    with override_login_service(app, service):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "purpose": "signup"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert service.requests == []


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (
            NexusError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Please try again later.",
                retryable=True,
            ),
            429,
        ),
        (
            NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The service is temporarily unavailable.",
                retryable=True,
            ),
            503,
        ),
    ],
)
def test_login_endpoint_uses_safe_existing_error_envelope(
    app: FastAPI,
    client: TestClient,
    error: NexusError,
    status_code: int,
) -> None:
    service = FakeLoginService(error=error)

    with override_login_service(app, service):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com"},
        )

    assert response.status_code == status_code
    assert response.json()["error"] == {
        "code": error.code,
        "message": error.message,
        "request_id": response.headers["X-Request-ID"],
    }
