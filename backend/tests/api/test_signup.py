from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from nexus.api.auth import get_signup_otp_service
from nexus.application.authentication.signup import SignupOtpRequest
from nexus.main import app


class FakeSignupService:
    def __init__(self) -> None:
        self.requests: list[SignupOtpRequest] = []

    def request_signup_otp(self, *, session: object, request: SignupOtpRequest) -> None:
        del session
        self.requests.append(request)


@contextmanager
def override_signup_service(service: FakeSignupService) -> Iterator[None]:
    app.dependency_overrides[get_signup_otp_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_signup_otp_service, None)


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
