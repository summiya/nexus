from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from nexus.application.authentication.signup import (
    SignupOtpRequest,
    SignupOtpService,
    normalize_display_text,
    normalize_signup_email,
)
from nexus.config.settings import Settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.mailer import EmailDeliveryError
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge
from nexus.infrastructure.rate_limit import RedisRateLimiter
from nexus.security.otp import digest_otp, generate_numeric_otp


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=["http://localhost:5173"],
        otp_hmac_secret="test-secret-value-with-enough-length",
        auth_token_secret="test-auth-token-secret-with-enough-length",
        refresh_token_secret="test-refresh-token-secret-with-enough-length",
        signup_otp_ttl_seconds=600,
        signup_otp_max_attempts=5,
        signup_otp_length=6,
        signup_otp_rate_limit_window_seconds=900,
        signup_otp_rate_limit_max_requests=5,
    )


@dataclass
class FakeEmailProvider:
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
            raise EmailDeliveryError("failed")
        self.sent.append({"email": email, "otp": otp, "expires_at": expires_at})


@dataclass
class FakeRateLimiter:
    allowed: bool = True
    calls: list[dict[str, Any]] = field(default_factory=list)

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        self.calls.append(
            {"key": key, "limit": limit, "window_seconds": window_seconds}
        )
        return self.allowed


class ScalarResult:
    def __init__(self, value: int | None) -> None:
        self.value = value


class FakeSession:
    def __init__(
        self,
        existing_user_id: int | None = None,
        *,
        fail_flush: bool = False,
    ) -> None:
        self.existing_user_id = existing_user_id
        self.fail_flush = fail_flush
        self.added: list[object] = []
        self.flushed = False
        self.committed = False
        self.rolled_back = False

    def scalar(self, _statement: object) -> int | None:
        return self.existing_user_id

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        if self.fail_flush:
            raise RuntimeError("flush failed")
        self.flushed = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def build_service(
    *,
    email_provider: FakeEmailProvider | None = None,
    rate_limiter: FakeRateLimiter | None = None,
) -> SignupOtpService:
    return SignupOtpService(
        settings=build_settings(),
        email_sender=email_provider or FakeEmailProvider(),
        rate_limiter=rate_limiter or FakeRateLimiter(),
    )


def signup_request(email: str = "  SUMMIYA@Acme.COM ") -> SignupOtpRequest:
    return SignupOtpRequest(
        organization_name=" Acme AI ",
        first_name=" Summiya ",
        last_name=" Rasheed ",
        email=email,
    )


def test_normalizes_display_text_without_slugifying() -> None:
    assert (
        normalize_display_text(" Acme AI ", "organization_name", max_length=255)
        == "Acme AI"
    )


def test_normalizes_and_validates_email() -> None:
    assert normalize_signup_email("  PERSON@Example.COM  ") == "person@example.com"
    with pytest.raises(NexusError) as exc_info:
        normalize_signup_email("not-an-email")
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


def test_creates_signup_challenge_and_sends_email() -> None:
    email_provider = FakeEmailProvider()
    session = FakeSession()

    result = build_service(email_provider=email_provider).request_signup_otp(
        session=session, request=signup_request()
    )

    assert result.accepted is True
    assert session.flushed is True
    assert session.committed is True
    assert len(email_provider.sent) == 1
    challenge = session.added[0]
    assert isinstance(challenge, OtpChallenge)
    assert challenge.email == "summiya@acme.com"
    assert challenge.purpose == "signup"
    assert challenge.user_id is None
    assert challenge.max_attempts == 5
    assert challenge.code_digest != email_provider.sent[0]["otp"]
    assert email_provider.sent[0]["otp"] not in challenge.code_digest


def test_existing_email_returns_generic_response_without_challenge_or_email() -> None:
    email_provider = FakeEmailProvider()
    session = FakeSession(existing_user_id=123)

    result = build_service(email_provider=email_provider).request_signup_otp(
        session=session, request=signup_request()
    )

    assert result.accepted is True
    assert session.added == []
    assert email_provider.sent == []
    assert session.committed is False


def test_email_provider_failure_rolls_back_and_raises_service_unavailable() -> None:
    session = FakeSession()

    with pytest.raises(NexusError) as exc_info:
        build_service(email_provider=FakeEmailProvider(fail=True)).request_signup_otp(
            session=session, request=signup_request()
        )

    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert session.rolled_back is True
    assert session.committed is False


def test_flush_failure_rolls_back_without_sending_email() -> None:
    email_provider = FakeEmailProvider()
    session = FakeSession(fail_flush=True)

    with pytest.raises(RuntimeError, match="flush failed"):
        build_service(email_provider=email_provider).request_signup_otp(
            session=session, request=signup_request()
        )

    assert email_provider.sent == []
    assert session.rolled_back is True
    assert session.committed is False


def test_rate_limit_exceeded_raises_rate_limited() -> None:
    with pytest.raises(NexusError) as exc_info:
        build_service(rate_limiter=FakeRateLimiter(allowed=False)).request_signup_otp(
            session=FakeSession(), request=signup_request()
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
