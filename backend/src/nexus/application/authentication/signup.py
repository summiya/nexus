"""Passwordless signup OTP request use case."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.config.settings import Settings
from nexus.domain.users import normalize_email
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.email import EmailDeliveryError, SignupOtpEmailProvider
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.rate_limit import RateLimiter, RateLimitError
from nexus.logging import get_logger
from nexus.security.otp import digest_otp, generate_numeric_otp, keyed_digest

logger = get_logger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SIGNUP_PURPOSE = "signup"


@dataclass(frozen=True)
class SignupOtpRequest:
    organization_name: str
    first_name: str
    last_name: str
    email: str


@dataclass(frozen=True)
class SignupOtpResult:
    accepted: bool = True


def normalize_display_text(value: str, field_name: str, *, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise NexusError(
            ErrorCode.VALIDATION_ERROR,
            "The request validation failed.",
            details={"field": field_name},
        )
    if len(normalized) > max_length:
        raise NexusError(
            ErrorCode.VALIDATION_ERROR,
            "The request validation failed.",
            details={"field": field_name},
        )
    return normalized


def normalize_signup_email(value: str) -> str:
    email = normalize_email(value)
    if len(email) > 320 or _EMAIL_RE.fullmatch(email) is None:
        raise NexusError(
            ErrorCode.VALIDATION_ERROR,
            "The request validation failed.",
            details={"field": "email"},
        )
    return email


class SignupOtpService:
    """Orchestrate signup OTP request behavior."""

    def __init__(
        self,
        *,
        settings: Settings,
        email_provider: SignupOtpEmailProvider,
        rate_limiter: RateLimiter,
    ) -> None:
        self._settings = settings
        self._email_provider = email_provider
        self._rate_limiter = rate_limiter

    def request_signup_otp(
        self,
        *,
        session: Session,
        request: SignupOtpRequest,
    ) -> SignupOtpResult:
        organization_name = normalize_display_text(
            request.organization_name,
            "organization_name",
            max_length=255,
        )
        first_name = normalize_display_text(
            request.first_name,
            "first_name",
            max_length=100,
        )
        last_name = normalize_display_text(
            request.last_name,
            "last_name",
            max_length=100,
        )
        email = normalize_signup_email(request.email)
        del organization_name, first_name, last_name

        self._enforce_rate_limit(email)

        user_exists = (
            session.scalar(select(User.id).where(User.email == email)) is not None
        )
        if user_exists:
            logger.info("signup_otp_request_accepted")
            return SignupOtpResult()

        otp = generate_numeric_otp(self._settings.signup_otp_length)
        expires_at = datetime.now(UTC) + timedelta(
            seconds=self._settings.signup_otp_ttl_seconds
        )
        challenge = OtpChallenge(
            user_id=None,
            email=email,
            purpose=_SIGNUP_PURPOSE,
            code_digest=digest_otp(
                secret=self._settings.otp_hmac_secret,
                email=email,
                purpose=_SIGNUP_PURPOSE,
                otp=otp,
            ),
            expires_at=expires_at,
            max_attempts=self._settings.signup_otp_max_attempts,
        )

        try:
            session.add(challenge)
            session.flush()
            self._email_provider.send_signup_otp(
                email=email,
                otp=otp,
                expires_at=expires_at,
            )
            session.commit()
        except EmailDeliveryError as exc:
            session.rollback()
            logger.warning("signup_otp_email_delivery_failed")
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The service is temporarily unavailable.",
                retryable=True,
            ) from exc
        except Exception:
            session.rollback()
            raise

        logger.info("signup_otp_request_accepted")
        return SignupOtpResult()

    def _enforce_rate_limit(self, email: str) -> None:
        key_digest = keyed_digest(
            secret=self._settings.otp_hmac_secret,
            message=f"signup-rate-limit:{email}",
        )
        try:
            allowed = self._rate_limiter.allow(
                key=f"signup-otp:{key_digest}",
                limit=self._settings.signup_otp_rate_limit_max_requests,
                window_seconds=self._settings.signup_otp_rate_limit_window_seconds,
            )
        except RateLimitError as exc:
            logger.warning("signup_otp_rate_limiter_unavailable")
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The service is temporarily unavailable.",
                retryable=True,
            ) from exc

        if not allowed:
            raise NexusError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Please try again later.",
                retryable=True,
            )
