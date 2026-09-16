"""Email delivery contracts and adapters."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage as SmtpMessage
from typing import Literal, Protocol


class EmailDeliveryError(Exception):
    """Raised when an email provider cannot deliver a message."""


@dataclass(frozen=True)
class EmailMessage:
    """Provider-neutral email message."""

    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailProvider(Protocol):
    """Provider-neutral outbound email contract."""

    def send(self, message: EmailMessage) -> None:
        """Deliver one email message."""


@dataclass(frozen=True)
class SmtpEmailProvider:
    """Generic SMTP adapter for outbound email delivery."""

    host: str
    port: int
    from_address: str
    username: str | None = None
    password: str | None = None
    security: Literal["starttls", "ssl", "none"] = "starttls"
    timeout_seconds: float = 10.0

    def send(self, message: EmailMessage) -> None:
        smtp_message = SmtpMessage()
        smtp_message["From"] = self.from_address
        smtp_message["To"] = message.to
        smtp_message["Subject"] = message.subject
        smtp_message.set_content(message.text_body)
        if message.html_body is not None:
            smtp_message.add_alternative(message.html_body, subtype="html")

        try:
            with self._connect() as client:
                if self.username is not None:
                    client.login(self.username, self.password or "")
                client.send_message(smtp_message)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError("Email delivery failed") from exc

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.security == "ssl":
            return smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=context,
            )

        client = smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds)
        if self.security == "starttls":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        return client


class SignupOtpEmailProvider(Protocol):
    """Focused contract used by the signup OTP use case."""

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        """Send a signup OTP to the supplied email address."""


@dataclass(frozen=True)
class SignupOtpEmailSender:
    """Compose signup OTP messages and delegate transport delivery."""

    provider: EmailProvider

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        expires_at_text = expires_at.strftime("%Y-%m-%d %H:%M UTC")
        self.provider.send(
            EmailMessage(
                to=email,
                subject="Your Nexus verification code",
                text_body=(
                    f"Your Nexus verification code is {otp}. "
                    f"It expires at {expires_at_text}. "
                    "If you did not request this code, you can ignore this email."
                ),
                html_body=(
                    "<p>Your Nexus verification code is "
                    f"<strong>{otp}</strong>.</p>"
                    f"<p>It expires at {expires_at_text}.</p>"
                    "<p>If you did not request this code, you can ignore this email.</p>"
                ),
            )
        )


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


def build_email_provider(
    *,
    provider_name: str,
    from_address: str,
    smtp_host: str | None = None,
    smtp_port: int = 587,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls",
) -> EmailProvider:
    """Build a provider-neutral outbound email adapter."""
    if provider_name != "smtp":
        raise EmailDeliveryError("Unsupported email provider")
    if not smtp_host:
        raise EmailDeliveryError("SMTP host is not configured")

    return SmtpEmailProvider(
        host=smtp_host,
        port=smtp_port,
        from_address=from_address,
        username=smtp_username,
        password=smtp_password,
        security=smtp_security,
    )


def build_signup_otp_email_provider(
    *,
    provider_name: str,
    from_address: str,
    smtp_host: str | None = None,
    smtp_port: int = 587,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls",
) -> SignupOtpEmailProvider:
    """Build the configured signup OTP sender."""
    if provider_name == "disabled":
        return DisabledSignupOtpEmailProvider()

    return SignupOtpEmailSender(
        provider=build_email_provider(
            provider_name=provider_name,
            from_address=from_address,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            smtp_security=smtp_security,
        )
    )
