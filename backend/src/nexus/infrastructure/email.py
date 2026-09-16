"""Email delivery contracts and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class EmailDeliveryError(Exception):
    """Raised when an email provider cannot deliver a message."""


class SignupOtpEmailProvider(Protocol):
    """Minimal contract for sending signup OTP messages."""

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        """Send a signup OTP to the supplied email address."""


@dataclass(frozen=True)
class DisabledSignupOtpEmailProvider:
    """Fail closed when no production email provider is configured."""

    provider_name: str = "disabled"

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        del email, otp, expires_at
        raise EmailDeliveryError("Signup OTP email provider is not configured")


def build_signup_otp_email_provider(provider_name: str) -> SignupOtpEmailProvider:
    """Build the configured signup OTP email provider."""
    if provider_name == "disabled":
        return DisabledSignupOtpEmailProvider()
    raise EmailDeliveryError("Unsupported signup OTP email provider")
