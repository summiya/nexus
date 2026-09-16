"""OTP challenge repository contracts."""

from __future__ import annotations

from typing import Protocol

from nexus.infrastructure.persistence.models.otp_challenge import OtpChallenge


class OtpChallengeRepository(Protocol):
    def add(self, challenge: OtpChallenge) -> None:
        """Persist an OTP challenge and flush generated fields."""

    def get_latest_for_update(
        self,
        *,
        email: str,
        purpose: str,
    ) -> OtpChallenge | None:
        """Return the latest matching challenge locked for update."""
