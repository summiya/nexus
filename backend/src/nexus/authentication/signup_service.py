"""Signup and OTP lifecycle."""

from __future__ import annotations

import hmac
import re
import unicodedata
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
from nexus.authentication.repository import (
    AuthenticationRepository,
    OtpChallenge,
    SignupAccount,
)
from nexus.authentication.session_service import SessionService
from nexus.domain.organizations import normalize_slug
from nexus.errors import ErrorCode, NexusError
from nexus.logging import get_logger
from nexus.ports.transaction import TransactionManager

logger = get_logger(__name__)

_OTP_RE = re.compile(r"^\d+$")
_SIGNUP_PURPOSE = "signup"


@dataclass(frozen=True)
class SignupPolicy:
    """Configuration values that directly control signup behavior."""

    otp_hmac_secret: str
    signup_otp_length: int
    signup_otp_ttl_seconds: int
    signup_otp_max_attempts: int
    signup_otp_rate_limit_max_requests: int
    signup_otp_rate_limit_window_seconds: int


@dataclass(frozen=True)
class SignupOtpRequest:
    organization_name: str
    first_name: str
    last_name: str
    email: str


@dataclass(frozen=True)
class SignupVerificationRequest:
    email: str
    otp: str
    organization_name: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class SignupVerificationResult:
    status: str
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class _OtpVerificationFailed(Exception):
    def __init__(self, *, persist_attempt_state: bool = False) -> None:
        super().__init__("OTP verification failed")
        self.persist_attempt_state = persist_attempt_state


@dataclass(frozen=True)
class SignupService:
    """Own signup validation, OTP lifecycle, and signup transactions."""

    policy: SignupPolicy
    transaction: TransactionManager
    repository: AuthenticationRepository
    session_service: SessionService
    email_gateway: AuthenticationEmailGateway
    rate_limiter: RateLimiter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def request_signup_otp(self, *, request: SignupOtpRequest) -> None:
        _normalize_display_text(
            request.organization_name,
            "organization_name",
            max_length=255,
        )
        _normalize_display_text(request.first_name, "first_name", max_length=100)
        _normalize_display_text(request.last_name, "last_name", max_length=100)
        email = normalize_auth_email(request.email)

        self._enforce_rate_limit(email)
        if self.repository.user_exists_by_email(email):
            self.transaction.commit()
            logger.info("signup_otp_request_accepted")
            return

        otp = generate_numeric_otp(self.policy.signup_otp_length)
        expires_at = self.clock() + timedelta(
            seconds=self.policy.signup_otp_ttl_seconds
        )
        challenge = OtpChallenge(
            public_id=uuid4(),
            email=email,
            purpose=_SIGNUP_PURPOSE,
            code_digest=digest_otp(
                secret=self.policy.otp_hmac_secret,
                email=email,
                purpose=_SIGNUP_PURPOSE,
                otp=otp,
            ),
            expires_at=expires_at,
            max_attempts=self.policy.signup_otp_max_attempts,
        )

        try:
            self.repository.add_otp_challenge(challenge)
            self.transaction.commit()
        except Exception:
            self.transaction.rollback()
            raise

        # The database transaction is closed before slow external email I/O.
        try:
            self.email_gateway.send_signup_otp(
                email=email,
                otp=otp,
                expires_at=expires_at,
            )
        except AuthenticationEmailError as exc:
            logger.warning("signup_otp_email_delivery_failed")
            raise _service_unavailable() from exc

        logger.info("signup_otp_request_accepted")

    def complete_signup(
        self,
        *,
        request: SignupVerificationRequest,
    ) -> SignupVerificationResult:
        organization_name = _normalize_display_text(
            request.organization_name,
            "organization_name",
            max_length=255,
        )
        first_name = _normalize_display_text(
            request.first_name,
            "first_name",
            max_length=100,
        )
        last_name = _normalize_display_text(
            request.last_name,
            "last_name",
            max_length=100,
        )
        organization_slug = _normalize_organization_slug(organization_name)
        display_name = f"{first_name} {last_name}"

        try:
            challenge = self._verify_signup_otp(
                email=request.email,
                otp=request.otp,
            )
            self._reject_existing_signup(
                email=challenge.email,
                organization_slug=organization_slug,
            )
            now = self.clock()
            identity = self.repository.create_organization_administrator(
                SignupAccount(
                    organization_public_id=uuid4(),
                    organization_name=organization_name,
                    organization_slug=organization_slug,
                    user_public_id=uuid4(),
                    email=challenge.email,
                    display_name=display_name,
                    email_verified_at=now,
                )
            )
            self.repository.update_otp_challenge(replace(challenge, consumed_at=now))
            token_result = self.session_service.stage_session(identity=identity)
            self.transaction.commit()
        except _OtpVerificationFailed as exc:
            try:
                if exc.persist_attempt_state:
                    self.transaction.commit()
                else:
                    self.transaction.rollback()
            except Exception:
                self.transaction.rollback()
                raise
            raise _invalid_credentials() from exc
        except Exception:
            self.transaction.rollback()
            raise

        # Signup is durable before best-effort welcome email delivery begins.
        try:
            self.email_gateway.send_welcome_email(
                email=challenge.email,
                display_name=display_name,
            )
        except AuthenticationEmailError:
            logger.warning("signup_welcome_email_delivery_failed")

        return SignupVerificationResult(
            status="completed",
            access_token=token_result.access_token,
            refresh_token=token_result.refresh_token,
            token_type=token_result.token_type,
            expires_in=token_result.expires_in,
        )

    def _verify_signup_otp(self, *, email: str, otp: str) -> OtpChallenge:
        normalized_email = normalize_auth_email(email)
        if len(otp) != self.policy.signup_otp_length or _OTP_RE.fullmatch(otp) is None:
            raise _OtpVerificationFailed()

        challenge = self.repository.get_latest_otp_challenge_for_update(
            email=normalized_email,
            purpose=_SIGNUP_PURPOSE,
        )
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.locked_at is not None
            or challenge.expires_at <= self.clock()
        ):
            raise _OtpVerificationFailed()

        expected_digest = digest_otp(
            secret=self.policy.otp_hmac_secret,
            email=normalized_email,
            purpose=_SIGNUP_PURPOSE,
            otp=otp,
        )
        if hmac.compare_digest(challenge.code_digest, expected_digest):
            return challenge

        attempt_count = challenge.attempt_count + 1
        self.repository.update_otp_challenge(
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
        raise _OtpVerificationFailed(persist_attempt_state=True)

    def _reject_existing_signup(
        self,
        *,
        email: str,
        organization_slug: str,
    ) -> None:
        if self.repository.user_exists_by_email(email):
            raise _conflict()
        if self.repository.organization_exists_by_slug(organization_slug):
            raise _conflict()

    def _enforce_rate_limit(self, email: str) -> None:
        key_digest = keyed_digest(
            secret=self.policy.otp_hmac_secret,
            message=f"signup-rate-limit:{email}",
        )
        try:
            allowed = self.rate_limiter.allow(
                key=f"signup-otp:{key_digest}",
                limit=self.policy.signup_otp_rate_limit_max_requests,
                window_seconds=(self.policy.signup_otp_rate_limit_window_seconds),
            )
        except RateLimitError as exc:
            logger.warning("signup_otp_rate_limiter_unavailable")
            raise _service_unavailable() from exc

        if not allowed:
            raise NexusError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Please try again later.",
                retryable=True,
            )


def _normalize_display_text(value: str, field_name: str, *, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or len(normalized) > max_length:
        raise _validation_error(field_name)
    return normalized


def _normalize_organization_slug(organization_name: str) -> str:
    try:
        slug = normalize_slug(organization_name)
    except ValueError as exc:
        raise _validation_error("organization_name") from exc
    if len(slug) > 128:
        raise _validation_error("organization_name")
    return slug


def _validation_error(field_name: str) -> NexusError:
    return NexusError(
        ErrorCode.VALIDATION_ERROR,
        "The request validation failed.",
        details={"field": field_name},
    )


def _invalid_credentials() -> NexusError:
    return NexusError(
        ErrorCode.UNAUTHORIZED,
        "Authentication credentials are invalid.",
    )


def _conflict() -> NexusError:
    return NexusError(
        ErrorCode.CONFLICT,
        "The request conflicts with the current resource state.",
    )


def _service_unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "The service is temporarily unavailable.",
        retryable=True,
    )
