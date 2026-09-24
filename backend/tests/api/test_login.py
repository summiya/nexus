from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.authentication.api.dependencies import get_login_service
from nexus.authentication.gateways import (
    AuthenticationEmailError,
    AuthenticationEmailGateway,
    RateLimiter,
)
from nexus.authentication.login_service import (
    LoginOtpRequest,
    LoginPolicy,
    LoginService,
    LoginVerificationRequest,
)
from nexus.authentication.repository import AuthenticationRepository
from nexus.authentication.session_service import SessionService, SessionTokenResult
from nexus.errors import ErrorCode, NexusError
from nexus.ports.transaction import TransactionManager


class FakeLoginService:
    def __init__(self, *, error: NexusError | None = None) -> None:
        self.error = error
        self.requests: list[LoginOtpRequest] = []
        self.verification_requests: list[LoginVerificationRequest] = []

    async def request_login_otp(self, *, request: LoginOtpRequest) -> None:
        self.requests.append(request)
        if self.error is not None:
            raise self.error

    async def verify_login_otp(
        self,
        *,
        request: LoginVerificationRequest,
    ) -> SessionTokenResult:
        self.verification_requests.append(request)
        if self.error is not None:
            raise self.error
        return SessionTokenResult(
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="bearer",
            expires_in=900,
        )


@contextmanager
def override_login_service(
    app: FastAPI,
    service: FakeLoginService | LoginService,
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


def test_login_verify_endpoint_returns_only_session_token_fields(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeLoginService()

    with override_login_service(app, service):
        response = client.post(
            "/api/v1/auth/login/verify",
            json={"email": "user@example.com", "otp": "123456"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "token_type": "bearer",
        "expires_in": 900,
    }
    assert service.verification_requests == [
        LoginVerificationRequest(email="user@example.com", otp="123456")
    ]


def test_login_verify_endpoint_returns_generic_unauthorized_error(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeLoginService(
        error=NexusError(
            ErrorCode.UNAUTHORIZED,
            "Authentication credentials are invalid.",
        )
    )

    with override_login_service(app, service):
        response = client.post(
            "/api/v1/auth/login/verify",
            json={"email": "unknown@example.com", "otp": "not-otp"},
        )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": ErrorCode.UNAUTHORIZED,
        "message": "Authentication credentials are invalid.",
        "request_id": response.headers["X-Request-ID"],
    }
    assert service.verification_requests == [
        LoginVerificationRequest(email="unknown@example.com", otp="not-otp")
    ]


def test_login_endpoint_returns_accepted_when_email_delivery_fails(
    app: FastAPI,
    client: TestClient,
) -> None:
    repository = Mock(spec=AuthenticationRepository)
    repository.user_exists_by_email.return_value = True
    transaction = Mock(spec=TransactionManager)
    email_gateway = Mock(spec=AuthenticationEmailGateway)
    email_gateway.send_login_otp.side_effect = AuthenticationEmailError("failed")
    rate_limiter = Mock(spec=RateLimiter)
    rate_limiter.allow.return_value = True
    service = LoginService(
        policy=LoginPolicy(
            otp_hmac_secret="test-secret-value-with-enough-length",
            otp_length=6,
            otp_ttl_seconds=600,
            otp_max_attempts=5,
            otp_rate_limit_max_requests=5,
            otp_rate_limit_window_seconds=900,
        ),
        transaction=transaction,
        repository=repository,
        session_service=Mock(spec=SessionService),
        email_gateway=email_gateway,
        rate_limiter=rate_limiter,
        clock=lambda: datetime(2026, 9, 22, tzinfo=UTC),
    )

    with override_login_service(app, service):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "registered@example.com"},
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    repository.add_otp_challenge.assert_awaited_once()
    transaction.commit.assert_awaited_once_with()
    transaction.rollback.assert_not_awaited()


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
