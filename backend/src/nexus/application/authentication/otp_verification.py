"""Reusable OTP verification use case."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.application.authentication.signup import normalize_signup_email
from nexus.config.settings import Settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge
from nexus.security.otp import digest_otp

OtpPurpose = Literal["signup", "login"]

_OTP_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class VerifiedOtpChallenge:
    challenge: OtpChallenge
    email: str
    purpose: OtpPurpose


class OtpVerificationFailed(Exception):
    """Raised when OTP verification fails without exposing challenge state."""

    def __init__(self, *, persist_attempt_state: bool = False) -> None:
        super().__init__("OTP verification failed")
        self.persist_attempt_state = persist_attempt_state


class OtpVerificationService:
    """Verify OTP challenges without owning the outer transaction."""

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def verify(
        self,
        *,
        session: Session,
        email: str,
        otp: str,
        purpose: OtpPurpose,
    ) -> VerifiedOtpChallenge:
        normalized_email = normalize_signup_email(email)
        self._validate_otp_format(otp)
        challenge = self._load_latest_challenge_for_update(
            session=session,
            email=normalized_email,
            purpose=purpose,
        )

        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.locked_at is not None
            or challenge.expires_at <= datetime.now(UTC)
        ):
            raise OtpVerificationFailed()

        expected_digest = digest_otp(
            secret=self._settings.otp_hmac_secret,
            email=normalized_email,
            purpose=purpose,
            otp=otp,
        )
        if not hmac.compare_digest(challenge.code_digest, expected_digest):
            challenge.attempt_count += 1
            if challenge.attempt_count >= challenge.max_attempts:
                challenge.locked_at = datetime.now(UTC)
            session.flush()
            raise OtpVerificationFailed(persist_attempt_state=True)

        return VerifiedOtpChallenge(
            challenge=challenge,
            email=normalized_email,
            purpose=purpose,
        )

    def _validate_otp_format(self, otp: str) -> None:
        if (
            len(otp) != self._settings.signup_otp_length
            or _OTP_RE.fullmatch(otp) is None
        ):
            raise OtpVerificationFailed()

    def _load_latest_challenge_for_update(
        self,
        *,
        session: Session,
        email: str,
        purpose: OtpPurpose,
    ) -> OtpChallenge | None:
        return session.scalar(
            select(OtpChallenge)
            .where(
                OtpChallenge.email == email,
                OtpChallenge.purpose == purpose,
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )


def otp_verification_error() -> NexusError:
    return NexusError(
        ErrorCode.UNAUTHORIZED,
        "Authentication credentials are invalid.",
    )
