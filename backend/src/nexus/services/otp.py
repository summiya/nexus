"""Reusable OTP verification service."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from nexus.config.settings import Settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge
from nexus.ports.repositories.otp_challenge import OtpChallengeRepository
from nexus.security.otp import digest_otp
from nexus.services.authentication_validation import normalize_auth_email

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

    def __init__(
        self,
        *,
        settings: Settings,
        otp_challenge_repository: OtpChallengeRepository,
    ) -> None:
        self._settings = settings
        self._otp_challenge_repository = otp_challenge_repository

    def verify(
        self,
        *,
        email: str,
        otp: str,
        purpose: OtpPurpose,
    ) -> VerifiedOtpChallenge:
        normalized_email = normalize_auth_email(email)
        self._validate_otp_format(otp)
        challenge = self._otp_challenge_repository.get_latest_for_update(
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


def otp_verification_error() -> NexusError:
    return NexusError(
        ErrorCode.UNAUTHORIZED,
        "Authentication credentials are invalid.",
    )
