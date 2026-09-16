from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import nexus.api.composition.authentication as authentication_composition
from nexus.api.composition.authentication import (
    build_email_provider,
    get_signup_otp_service,
    get_signup_verification_service,
)
from nexus.application.authentication.signup import SignupOtpRequest
from nexus.application.authentication.signup_verification import (
    SignupVerificationRequest,
    SignupVerificationResult,
)
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.mailer.providers import ResendEmailProvider
from nexus.main import app


class FakeTransaction:
    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class FakeUserRepository:
    def exists_by_email(self, email: str) -> bool:
        del email
        return False


class FakeOtpChallengeRepository:
    pass


class FakeSignupService:
    def __init__(self) -> None:
        self.requests: list[SignupOtpRequest] = []

    def request_signup_otp(self, *, request: SignupOtpRequest) -> None:
        self.requests.append(request)


class FakeSignupVerificationService:
    def __init__(self) -> None:
        self.requests: list[SignupVerificationRequest] = []

    def complete_signup(
        self,
        *,
        request: SignupVerificationRequest,
    ) -> SignupVerificationResult:
        self.requests.append(request)
        return SignupVerificationResult(
            status="completed",
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="bearer",
            expires_in=900,
        )


@contextmanager
def override_signup_service(service: FakeSignupService) -> Iterator[None]:
    app.dependency_overrides[get_signup_otp_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_signup_otp_service, None)


@contextmanager
def override_signup_verification_service(
    service: FakeSignupVerificationService,
) -> Iterator[None]:
    app.dependency_overrides[get_signup_verification_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(
            get_signup_verification_service,
            None,
        )


def test_signup_endpoint_returns_generic_accepted_response(client: TestClient) -> None:
    service = FakeSignupService()
    with override_signup_service(service):
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
    assert service.requests == [
        SignupOtpRequest(
            organization_name="Acme AI",
            first_name="Summiya",
            last_name="Rasheed",
            email="summiya@acme.com",
        )
    ]


def test_signup_endpoint_rejects_client_supplied_purpose(client: TestClient) -> None:
    service = FakeSignupService()
    with override_signup_service(service):
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
    assert service.requests == []


def test_signup_verify_endpoint_returns_completed_response(
    client: TestClient,
) -> None:
    service = FakeSignupVerificationService()
    with override_signup_verification_service(service):
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
    assert service.requests == [
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
    client: TestClient,
    missing_field: str,
) -> None:
    service = FakeSignupVerificationService()
    body = {
        "email": "summiya@acme.com",
        "otp": "123456",
        "organization_name": "Acme AI",
        "first_name": "Summiya",
        "last_name": "Rasheed",
    }
    body.pop(missing_field)

    with override_signup_verification_service(service):
        response = client.post("/api/v1/auth/signup/verify", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert service.requests == []


def test_build_email_provider_uses_resend_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authentication_composition.settings, "email_provider", "resend")
    monkeypatch.setattr(
        authentication_composition.settings,
        "email_from_address",
        "no-reply@example.com",
    )
    monkeypatch.setattr(
        authentication_composition.settings,
        "resend_api_key",
        "test-resend-key",
    )

    provider = build_email_provider()

    assert provider == ResendEmailProvider(
        api_key="test-resend-key",
        from_address="no-reply@example.com",
    )


def test_build_email_provider_fails_closed_without_resend_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authentication_composition.settings, "email_provider", "resend")
    monkeypatch.setattr(authentication_composition.settings, "resend_api_key", None)

    with pytest.raises(authentication_composition.EmailDeliveryError):
        build_email_provider()


def test_get_signup_otp_service_maps_email_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authentication_composition.settings, "email_provider", "disabled"
    )

    with pytest.raises(NexusError) as exc_info:
        get_signup_otp_service(
            session=object(),  # type: ignore[arg-type]
        )

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
