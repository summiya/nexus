"""Authentication email composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from nexus.infrastructure.mailer import EmailMessage, EmailProvider


class SignupOtpEmailSender(Protocol):
    """Contract for sending signup OTP emails."""

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        """Send a signup OTP email."""


class WelcomeEmailSender(Protocol):
    """Contract for sending signup welcome emails."""

    def send_welcome_email(
        self,
        *,
        email: str,
        display_name: str,
    ) -> None:
        """Send a welcome email."""


@dataclass(frozen=True)
class DefaultSignupOtpEmailSender:
    """Compose Nexus signup OTP emails and delegate delivery."""

    email_provider: EmailProvider

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        message = EmailMessage(
            to=email,
            subject="Your NEXUS signup code",
            text_body=(
                "Use this code to continue signing up for NEXUS: "
                f"{otp}\n\n"
                f"This code expires at {expires_at.isoformat()}."
            ),
        )
        self.email_provider.send(message)


@dataclass(frozen=True)
class DefaultWelcomeEmailSender:
    """Compose Nexus welcome emails and delegate delivery."""

    email_provider: EmailProvider

    def send_welcome_email(
        self,
        *,
        email: str,
        display_name: str,
    ) -> None:
        message = EmailMessage(
            to=email,
            subject="Welcome to NEXUS",
            text_body=f"Welcome to NEXUS, {display_name}.",
        )
        self.email_provider.send(message)
