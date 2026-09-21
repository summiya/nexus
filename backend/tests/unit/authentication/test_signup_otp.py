from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from nexus.application.authentication.gateways import AuthenticationEmailError
from nexus.application.authentication.repository import OtpChallenge
from nexus.application.authentication.service import (
    SignupOtpRequest,
    SignupPolicy,
    SignupService,
)
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.rate_limit import RedisRateLimiter
from nexus.security.otp import digest_otp, generate_numeric_otp


def policy() -> SignupPolicy:
    return SignupPolicy(
        otp_hmac_secret="test-secret-value-with-enough-length",
        signup_otp_ttl_seconds=600,
        signup_otp_max_attempts=5,
        signup_otp_length=6,
        signup_otp_rate_limit_window_seconds=900,
        signup_otp_rate_limit_max_requests=5,
    )


@dataclass
class FakeEmailGateway:
    fail: bool = False
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        if self.fail:
            raise AuthenticationEmailError("failed")
        self.sent.append({"email": email, "otp": otp, "expires_at": expires_at})

    def send_welcome_email(self, *, email: str, display_name: str) -> None:
        del email, display_name


@dataclass
class FakeRateLimiter:
    allowed: bool = True
    calls: list[dict[str, Any]] = field(default_factory=list)

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        self.calls.append(
            {"key": key, "limit": limit, "window_seconds": window_seconds}
        )
        return self.allowed


class FakeTransaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeAuthenticationRepository:
    def __init__(
        self,
        *,
        existing_user: bool = False,
        fail_add: bool = False,
    ) -> None:
        self.existing_user = existing_user
        self.fail_add = fail_add
        self.added: list[OtpChallenge] = []

    def user_exists_by_email(self, email: str) -> bool:
        del email
        return self.existing_user

    def add_otp_challenge(self, challenge: OtpChallenge) -> None:
        if self.fail_add:
            raise RuntimeError("flush failed")
        self.added.append(challenge)


def build_service(
    *,
    email_gateway: FakeEmailGateway | None = None,
    rate_limiter: FakeRateLimiter | None = None,
    transaction: FakeTransaction | None = None,
    repository: FakeAuthenticationRepository | None = None,
) -> SignupService:
    return SignupService(
        policy=policy(),
        transaction=transaction or FakeTransaction(),
        repository=repository or FakeAuthenticationRepository(),  # type: ignore[arg-type]
        session_service=None,  # type: ignore[arg-type]
        email_gateway=email_gateway or FakeEmailGateway(),
        rate_limiter=rate_limiter or FakeRateLimiter(),
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )


def signup_request(email: str = "  SUMMIYA@Acme.COM ") -> SignupOtpRequest:
    return SignupOtpRequest(
        organization_name=" Acme AI ",
        first_name=" Summiya ",
        last_name=" Rasheed ",
        email=email,
    )


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(NexusError) as exc_info:
        build_service().request_signup_otp(request=signup_request("not-an-email"))

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


def test_otp_generation_and_digest_do_not_store_plaintext() -> None:
    otp = generate_numeric_otp(6)
    digest = digest_otp(
        secret="test-secret-value-with-enough-length",
        email="person@example.com",
        purpose="signup",
        otp=otp,
    )

    assert otp.isdigit()
    assert len(otp) == 6
    assert digest != otp
    assert otp not in digest


def test_creates_signup_challenge_and_sends_email_after_commit() -> None:
    email_gateway = FakeEmailGateway()
    transaction = FakeTransaction()
    repository = FakeAuthenticationRepository()

    build_service(
        email_gateway=email_gateway,
        transaction=transaction,
        repository=repository,
    ).request_signup_otp(request=signup_request())

    assert transaction.committed is True
    assert len(email_gateway.sent) == 1
    challenge = repository.added[0]
    assert challenge.email == "summiya@acme.com"
    assert challenge.purpose == "signup"
    assert challenge.max_attempts == 5
    assert challenge.code_digest != email_gateway.sent[0]["otp"]
    assert email_gateway.sent[0]["otp"] not in challenge.code_digest


def test_existing_email_returns_generic_response_without_challenge_or_email() -> None:
    email_gateway = FakeEmailGateway()
    transaction = FakeTransaction()
    repository = FakeAuthenticationRepository(existing_user=True)

    build_service(
        email_gateway=email_gateway,
        transaction=transaction,
        repository=repository,
    ).request_signup_otp(request=signup_request())

    assert repository.added == []
    assert email_gateway.sent == []
    assert transaction.committed is True


def test_email_failure_keeps_committed_challenge_and_reports_unavailable() -> None:
    transaction = FakeTransaction()

    with pytest.raises(NexusError) as exc_info:
        build_service(
            email_gateway=FakeEmailGateway(fail=True),
            transaction=transaction,
        ).request_signup_otp(request=signup_request())

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert transaction.committed is True
    assert transaction.rolled_back is False


def test_flush_failure_rolls_back_without_sending_email() -> None:
    email_gateway = FakeEmailGateway()
    transaction = FakeTransaction()

    with pytest.raises(RuntimeError, match="flush failed"):
        build_service(
            email_gateway=email_gateway,
            transaction=transaction,
            repository=FakeAuthenticationRepository(fail_add=True),
        ).request_signup_otp(request=signup_request())

    assert email_gateway.sent == []
    assert transaction.rolled_back is True
    assert transaction.committed is False


def test_rate_limit_exceeded_raises_rate_limited() -> None:
    with pytest.raises(NexusError) as exc_info:
        build_service(rate_limiter=FakeRateLimiter(allowed=False)).request_signup_otp(
            request=signup_request()
        )

    assert exc_info.value.code == ErrorCode.RATE_LIMITED


class FakeRedis:
    def __init__(self, allowed: int = 1) -> None:
        self.allowed = allowed
        self.eval_calls: list[tuple[str, int, str, str, str]] = []

    def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        limit: str,
        window_seconds: str,
    ) -> int:
        self.eval_calls.append((script, numkeys, key, limit, window_seconds))
        return self.allowed


def test_redis_rate_limiter_uses_atomic_script() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis=redis)  # type: ignore[arg-type]

    assert limiter.allow(key="signup-otp:key", limit=5, window_seconds=900) is True

    assert len(redis.eval_calls) == 1
    script, numkeys, key, limit, window_seconds = redis.eval_calls[0]
    assert "INCR" in script
    assert "EXPIRE" in script
    assert numkeys == 1
    assert key == "signup-otp:key"
    assert limit == "5"
    assert window_seconds == "900"
