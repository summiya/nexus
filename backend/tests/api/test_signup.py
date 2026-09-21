from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.api.composition.authentication import build_email_provider
from nexus.api.dependencies.authentication import (
    get_signup_service,
)
from nexus.application.authentication.service import (
    SignupOtpRequest,
    SignupVerificationRequest,
    SignupVerificationResult,
)
from nexus.config.settings import Settings
from nexus.errors import ErrorCode
from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage
from nexus.infrastructure.mailer.providers import ResendEmailProvider


class FakeSignupService:
    def __init__(self) -> None:
        self.otp_requests: list[SignupOtpRequest] = []
        self.verification_requests: list[SignupVerificationRequest] = []

    def request_signup_otp(self, *, request: SignupOtpRequest) -> None:
        self.otp_requests.append(request)

    def complete_signup(
        self,
        *,
        request: SignupVerificationRequest,
    ) -> SignupVerificationResult:
        self.verification_requests.append(request)
        return SignupVerificationResult(
            status="completed",
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="bearer",
            expires_in=900,
        )


def build_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ["https://nexus.example"],
        "otp_hmac_secret": "test-secret-value-with-enough-length",
        "auth_token_secret": "test-auth-token-secret-with-enough-length",
        "refresh_token_secret": "test-refresh-token-secret-with-enough-length",
        **overrides,
    }
    return Settings(_env_file=None, **values)


@contextmanager
def override_signup_service(
    app: FastAPI,
    service: FakeSignupService,
) -> Iterator[None]:
    app.dependency_overrides[get_signup_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_signup_service, None)


def test_signup_endpoint_returns_generic_accepted_response(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeSignupService()
    with override_signup_service(app, service):
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": "Acme AI",
                "first_name": "Summiya",
                "last_name": "Rasheed",
                "email": "summiya@acme.com",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert service.otp_requests == [
        SignupOtpRequest(
            organization_name="Acme AI",
            first_name="Summiya",
            last_name="Rasheed",
            email="summiya@acme.com",
        )
    ]


def test_signup_endpoint_rejects_client_supplied_purpose(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeSignupService()
    with override_signup_service(app, service):
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "organization_name": "Acme AI",
                "first_name": "Summiya",
                "last_name": "Rasheed",
                "email": "summiya@acme.com",
                "purpose": "login",
            },
        )

    assert response.status_code == 422
    assert service.otp_requests == []


def test_signup_verify_endpoint_returns_completed_response(
    app: FastAPI,
    client: TestClient,
) -> None:
    service = FakeSignupService()
    with override_signup_service(app, service):
        response = client.post(
            "/api/v1/auth/signup/verify",
            json={
                "email": "summiya@acme.com",
                "otp": "123456",
                "organization_name": "Acme AI",
                "first_name": "Summiya",
                "last_name": "Rasheed",
            },
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
        SignupVerificationRequest(
            email="summiya@acme.com",
            otp="123456",
            organization_name="Acme AI",
            first_name="Summiya",
            last_name="Rasheed",
        )
    ]


@pytest.mark.parametrize(
    "missing_field",
    ["email", "otp", "organization_name", "first_name", "last_name"],
)
def test_signup_verify_endpoint_requires_all_fields(
    app: FastAPI,
    client: TestClient,
    missing_field: str,
) -> None:
    service = FakeSignupService()
    body = {
        "email": "summiya@acme.com",
        "otp": "123456",
        "organization_name": "Acme AI",
        "first_name": "Summiya",
        "last_name": "Rasheed",
    }
    body.pop(missing_field)

    with override_signup_service(app, service):
        response = client.post("/api/v1/auth/signup/verify", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert service.verification_requests == []


def test_build_email_provider_uses_resend_settings() -> None:
    provider = build_email_provider(
        build_settings(
            email_provider="resend",
            email_from_address="no-reply@example.com",
            resend_api_key="test-resend-key",
        )
    )

    assert provider == ResendEmailProvider(
        api_key="test-resend-key",
        from_address="no-reply@example.com",
    )


def test_build_email_provider_fails_closed_without_resend_key() -> None:
    with pytest.raises(EmailDeliveryError):
        build_email_provider(
            build_settings(
                email_provider="resend",
                resend_api_key=None,
            )
        )


def test_disabled_email_provider_fails_safely_when_used() -> None:
    provider = build_email_provider(build_settings(email_provider="disabled"))

    with pytest.raises(EmailDeliveryError):
        provider.send(
            EmailMessage(
                to="user@example.com",
                subject="Test",
                text_body="Test",
            )
        )
