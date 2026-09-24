"""Login OTP request lifecycle."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
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
from nexus.authentication.session_service import SessionService, SessionTokenResult
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.ports.transaction import TransactionManager

logger = get_logger(__name__)

_OTP_RE = re.compile(r"^\d+$")
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
class LoginVerificationRequest:
    email: str
    otp: str


class _LoginOtpVerificationFailed(Exception):
    def __init__(self, *, persist_attempt_state: bool = False) -> None:
        super().__init__("Login OTP verification failed")
        self.persist_attempt_state = persist_attempt_state


@dataclass(frozen=True)
class LoginService:
    """Own login OTP requests, verification, and login transactions."""

    policy: LoginPolicy
    transaction: TransactionManager
    repository: AuthenticationRepository
    session_service: SessionService
    email_gateway: AuthenticationEmailGateway
    rate_limiter: RateLimiter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def request_login_otp(self, *, request: LoginOtpRequest) -> None:
        email = normalize_auth_email(request.email)
        await self._enforce_rate_limit(email)

        try:
            if not await self.repository.user_exists_by_email(email):
                await self.transaction.commit()
                logger.info("login_otp_request_accepted")
                return

            otp = generate_numeric_otp(self.policy.otp_length)
            expires_at = self.clock() + timedelta(seconds=self.policy.otp_ttl_seconds)
            await self.repository.add_otp_challenge(
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
            await self.transaction.commit()
        except Exception:
            await self.transaction.rollback()
            raise

        # The database transaction is closed before slow external email I/O.
        try:
            await self.email_gateway.send_login_otp(
                email=email,
                otp=otp,
                expires_at=expires_at,
            )
        except AuthenticationEmailError:
            logger.warning("login_otp_email_delivery_failed")

        logger.info("login_otp_request_accepted")

    async def verify_login_otp(
        self,
        *,
        request: LoginVerificationRequest,
    ) -> SessionTokenResult:
        try:
            challenge = await self._verify_login_otp(
                email=request.email,
                otp=request.otp,
            )
            identity = await self.repository.get_identity_by_email(challenge.email)
            if identity is None:
                raise _LoginOtpVerificationFailed()

            await self.repository.update_otp_challenge(
                replace(challenge, consumed_at=self.clock())
            )
            token_result = await self.session_service.stage_session(identity=identity)
            await self.transaction.commit()
            return token_result
        except _LoginOtpVerificationFailed as exc:
            try:
                if exc.persist_attempt_state:
                    await self.transaction.commit()
                else:
                    await self.transaction.rollback()
            except Exception:
                await self.transaction.rollback()
                raise
            raise _invalid_credentials() from exc
        except Exception:
            await self.transaction.rollback()
            raise

    async def _verify_login_otp(self, *, email: str, otp: str) -> OtpChallenge:
        normalized_email = normalize_auth_email(email)
        if len(otp) != self.policy.otp_length or _OTP_RE.fullmatch(otp) is None:
            raise _LoginOtpVerificationFailed()

        challenge = await self.repository.get_latest_otp_challenge_for_update(
            email=normalized_email,
            purpose=_LOGIN_PURPOSE,
        )
        if (
            challenge is None
            or challenge.purpose != _LOGIN_PURPOSE
            or challenge.consumed_at is not None
            or challenge.locked_at is not None
            or challenge.expires_at <= self.clock()
        ):
            raise _LoginOtpVerificationFailed()

        expected_digest = digest_otp(
            secret=self.policy.otp_hmac_secret,
            email=normalized_email,
            purpose=_LOGIN_PURPOSE,
            otp=otp,
        )
        if hmac.compare_digest(challenge.code_digest, expected_digest):
            return challenge

        attempt_count = challenge.attempt_count + 1
        await self.repository.update_otp_challenge(
            replace(
                challenge,
                attempt_count=attempt_count,
                locked_at=(
                    self.clock()
                    if attempt_count >= challenge.max_attempts
                    else challenge.locked_at
                ),
            )
        )
        raise _LoginOtpVerificationFailed(persist_attempt_state=True)

    async def _enforce_rate_limit(self, email: str) -> None:
        key_digest = keyed_digest(
            secret=self.policy.otp_hmac_secret,
            message=f"login-rate-limit:{email}",
        )
        try:
            allowed = await self.rate_limiter.allow(
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


def _invalid_credentials() -> NexusError:
    return NexusError(
        ErrorCode.UNAUTHORIZED,
        "Authentication credentials are invalid.",
    )
