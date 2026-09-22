from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest

from nexus.authentication.gateways import (
    AuthenticationEmailError,
    RateLimitError,
)
from nexus.authentication.login_service import (
    LoginOtpRequest,
    LoginPolicy,
    LoginService,
)
from nexus.authentication.otp import digest_otp, keyed_digest
from nexus.authentication.repository import OtpChallenge
from nexus.errors import ErrorCode, NexusError

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
OTP_SECRET = "test-secret-value-with-enough-length"


def policy() -> LoginPolicy:
    return LoginPolicy(
        otp_hmac_secret=OTP_SECRET,
        otp_length=6,
        otp_ttl_seconds=600,
        otp_max_attempts=5,
        otp_rate_limit_max_requests=5,
        otp_rate_limit_window_seconds=900,
    )


@dataclass
class FakeRepository:
    existing_user: bool = True
    fail_add: bool = False
    checked_emails: list[str] = field(default_factory=list)
    added: list[OtpChallenge] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def user_exists_by_email(self, email: str) -> bool:
        self.checked_emails.append(email)
        return self.existing_user

    def add_otp_challenge(self, challenge: OtpChallenge) -> None:
        if self.fail_add:
            raise RuntimeError("flush failed")
        self.added.append(challenge)
        self.events.append("challenge")


@dataclass
class FakeEmailGateway:
    fail: bool = False
    sent: list[dict[str, Any]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def send_login_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        self.events.append("email")
        if self.fail:
            raise AuthenticationEmailError("failed")
        self.sent.append({"email": email, "otp": otp, "expires_at": expires_at})

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        del email, otp, expires_at

    def send_welcome_email(self, *, email: str, display_name: str) -> None:
        del email, display_name


@dataclass
class FakeRateLimiter:
    allowed: bool = True
    fail: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        self.calls.append(
            {"key": key, "limit": limit, "window_seconds": window_seconds}
        )
        if self.fail:
            raise RateLimitError("unavailable")
        return self.allowed


@dataclass
class FakeTransaction:
    events: list[str] = field(default_factory=list)
    commit_count: int = 0
    rollback_count: int = 0

    def commit(self) -> None:
        self.commit_count += 1
        self.events.append("commit")

    def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("rollback")


def build_service(
    *,
    repository: FakeRepository | None = None,
    email_gateway: FakeEmailGateway | None = None,
    rate_limiter: FakeRateLimiter | None = None,
    transaction: FakeTransaction | None = None,
) -> LoginService:
    return LoginService(
        policy=policy(),
        transaction=transaction or FakeTransaction(),
        repository=repository or FakeRepository(),  # type: ignore[arg-type]
        email_gateway=email_gateway or FakeEmailGateway(),
        rate_limiter=rate_limiter or FakeRateLimiter(),
        clock=lambda: NOW,
    )


def test_registered_email_creates_login_challenge_and_emails_after_commit() -> None:
    events: list[str] = []
    repository = FakeRepository(events=events)
    transaction = FakeTransaction(events=events)
    email_gateway = FakeEmailGateway(events=events)
    rate_limiter = FakeRateLimiter()

    build_service(
        repository=repository,
        transaction=transaction,
        email_gateway=email_gateway,
        rate_limiter=rate_limiter,
    ).request_login_otp(request=LoginOtpRequest(email="  USER@Example.COM "))

    assert repository.checked_emails == ["user@example.com"]
    assert events == ["challenge", "commit", "email"]
    assert transaction.commit_count == 1
    assert transaction.rollback_count == 0
    challenge = repository.added[0]
    sent = email_gateway.sent[0]
    assert challenge.email == "user@example.com"
    assert challenge.purpose == "login"
    assert challenge.max_attempts == 5
    assert challenge.expires_at == NOW.replace(minute=10)
    assert challenge.code_digest != sent["otp"]
    assert sent["otp"] not in challenge.code_digest
    assert sent == {
        "email": "user@example.com",
        "otp": sent["otp"],
        "expires_at": NOW.replace(minute=10),
    }
    assert rate_limiter.calls == [
        {
            "key": (
                "login-otp:"
                + keyed_digest(
                    secret=OTP_SECRET,
                    message="login-rate-limit:user@example.com",
                )
            ),
            "limit": 5,
            "window_seconds": 900,
        }
    ]
    assert "user@example.com" not in rate_limiter.calls[0]["key"]


def test_unknown_email_returns_without_challenge_or_email() -> None:
    repository = FakeRepository(existing_user=False)
    transaction = FakeTransaction()
    email_gateway = FakeEmailGateway()
    rate_limiter = FakeRateLimiter()

    result = build_service(
        repository=repository,
        transaction=transaction,
        email_gateway=email_gateway,
        rate_limiter=rate_limiter,
    ).request_login_otp(request=LoginOtpRequest(email="unknown@example.com"))

    assert result is None
    assert repository.checked_emails == ["unknown@example.com"]
    assert repository.added == []
    assert email_gateway.sent == []
    assert transaction.commit_count == 1
    assert transaction.rollback_count == 0
    assert len(rate_limiter.calls) == 1


def test_invalid_email_is_rejected_before_rate_limit_or_lookup() -> None:
    repository = FakeRepository()
    rate_limiter = FakeRateLimiter()

    with pytest.raises(NexusError) as exc_info:
        build_service(
            repository=repository,
            rate_limiter=rate_limiter,
        ).request_login_otp(request=LoginOtpRequest(email="not-an-email"))

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR
    assert repository.checked_emails == []
    assert rate_limiter.calls == []


def test_signup_and_login_otp_digests_are_isolated_by_purpose() -> None:
    values = {
        "secret": OTP_SECRET,
        "email": "user@example.com",
        "otp": "123456",
    }

    assert digest_otp(purpose="signup", **values) != digest_otp(
        purpose="login", **values
    )


def test_rate_limit_rejection_happens_before_account_lookup() -> None:
    repository = FakeRepository()

    with pytest.raises(NexusError) as exc_info:
        build_service(
            repository=repository,
            rate_limiter=FakeRateLimiter(allowed=False),
        ).request_login_otp(request=LoginOtpRequest(email="user@example.com"))

    assert exc_info.value.code == ErrorCode.RATE_LIMITED
    assert repository.checked_emails == []


def test_rate_limiter_failure_returns_safe_service_unavailable() -> None:
    with pytest.raises(NexusError) as exc_info:
        build_service(
            rate_limiter=FakeRateLimiter(fail=True),
        ).request_login_otp(request=LoginOtpRequest(email="user@example.com"))

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert exc_info.value.message == "The service is temporarily unavailable."


def test_persistence_failure_rolls_back_without_sending_email() -> None:
    transaction = FakeTransaction()
    email_gateway = FakeEmailGateway()

    with pytest.raises(RuntimeError, match="flush failed"):
        build_service(
            repository=FakeRepository(fail_add=True),
            transaction=transaction,
            email_gateway=email_gateway,
        ).request_login_otp(request=LoginOtpRequest(email="user@example.com"))

    assert transaction.commit_count == 0
    assert transaction.rollback_count == 1
    assert email_gateway.sent == []


def test_email_failure_keeps_committed_challenge_and_returns_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository()
    transaction = FakeTransaction()
    test_logger = Mock()
    monkeypatch.setattr(
        "nexus.authentication.login_service.generate_numeric_otp",
        lambda _length: "123456",
    )
    monkeypatch.setattr(
        "nexus.authentication.login_service.logger",
        test_logger,
    )

    result = build_service(
        repository=repository,
        transaction=transaction,
        email_gateway=FakeEmailGateway(fail=True),
    ).request_login_otp(request=LoginOtpRequest(email="user@example.com"))

    assert result is None
    assert len(repository.added) == 1
    assert transaction.commit_count == 1
    assert transaction.rollback_count == 0
    test_logger.warning.assert_called_once_with("login_otp_email_delivery_failed")
    logged_calls = repr(test_logger.mock_calls)
    assert "user@example.com" not in logged_calls
    assert "123456" not in logged_calls
