"""Login OTP request lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexus.authentication.gateways import (
    AuthenticationEmailError,
    AuthenticationEmailGateway,
    RateLimiter,
    RateLimitError,
)
from nexus.authentication.otp import (
    digest_otp,
    generate_numeric_otp,
    keyed_digest,
    normalize_auth_email,
)
from nexus.authentication.repository import AuthenticationRepository, OtpChallenge
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.ports.transaction import TransactionManager

logger = get_logger(__name__)

_LOGIN_PURPOSE = "login"


@dataclass(frozen=True)
class LoginPolicy:
    """Configuration values that directly control login OTP requests."""

    otp_hmac_secret: str
    otp_length: int
    otp_ttl_seconds: int
    otp_max_attempts: int
    otp_rate_limit_max_requests: int
    otp_rate_limit_window_seconds: int


@dataclass(frozen=True)
class LoginOtpRequest:
    email: str


@dataclass(frozen=True)
class LoginService:
    """Request login OTPs without revealing whether an account exists."""

    policy: LoginPolicy
    transaction: TransactionManager
    repository: AuthenticationRepository
    email_gateway: AuthenticationEmailGateway
    rate_limiter: RateLimiter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def request_login_otp(self, *, request: LoginOtpRequest) -> None:
        email = normalize_auth_email(request.email)
        self._enforce_rate_limit(email)

        try:
            if not self.repository.user_exists_by_email(email):
                self.transaction.commit()
                logger.info("login_otp_request_accepted")
                return

            otp = generate_numeric_otp(self.policy.otp_length)
            expires_at = self.clock() + timedelta(seconds=self.policy.otp_ttl_seconds)
            self.repository.add_otp_challenge(
                OtpChallenge(
                    public_id=uuid4(),
                    email=email,
                    purpose=_LOGIN_PURPOSE,
                    code_digest=digest_otp(
                        secret=self.policy.otp_hmac_secret,
                        email=email,
                        purpose=_LOGIN_PURPOSE,
                        otp=otp,
                    ),
                    expires_at=expires_at,
                    max_attempts=self.policy.otp_max_attempts,
                )
            )
            self.transaction.commit()
        except Exception:
            self.transaction.rollback()
            raise

        # The database transaction is closed before slow external email I/O.
        try:
            self.email_gateway.send_login_otp(
                email=email,
                otp=otp,
                expires_at=expires_at,
            )
        except AuthenticationEmailError as exc:
            logger.warning("login_otp_email_delivery_failed")
            raise _service_unavailable() from exc

        logger.info("login_otp_request_accepted")

    def _enforce_rate_limit(self, email: str) -> None:
        key_digest = keyed_digest(
            secret=self.policy.otp_hmac_secret,
            message=f"login-rate-limit:{email}",
        )
        try:
            allowed = self.rate_limiter.allow(
                key=f"login-otp:{key_digest}",
                limit=self.policy.otp_rate_limit_max_requests,
                window_seconds=self.policy.otp_rate_limit_window_seconds,
            )
        except RateLimitError as exc:
            logger.warning("login_otp_rate_limiter_unavailable")
            raise _service_unavailable() from exc

        if not allowed:
            raise NexusError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Please try again later.",
                retryable=True,
            )


def _service_unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "The service is temporarily unavailable.",
        retryable=True,
    )
