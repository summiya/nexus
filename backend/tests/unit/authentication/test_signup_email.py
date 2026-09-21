from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from nexus.authentication.gateways import AuthenticationEmailError
from nexus.infrastructure.authentication import ProviderAuthenticationEmailGateway
from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage


@dataclass
class FakeEmailProvider:
    fail: bool = False
    messages: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailDeliveryError("failed")
        self.messages.append(message)


def test_signup_otp_email_sender_composes_and_delegates_message() -> None:
    provider = FakeEmailProvider()
    expires_at = datetime(2026, 9, 16, 12, 30, tzinfo=UTC)

    ProviderAuthenticationEmailGateway(email_provider=provider).send_signup_otp(
        email="person@example.com",
        otp="123456",
        expires_at=expires_at,
    )

    assert provider.messages == [
        EmailMessage(
            to="person@example.com",
            subject="Your NEXUS signup code",
            text_body=(
                "Use this code to continue signing up for NEXUS: 123456\n\n"
                "This code expires at 2026-09-16T12:30:00+00:00."
            ),
        )
    ]


def test_signup_otp_email_sender_propagates_delivery_failure() -> None:
    with pytest.raises(AuthenticationEmailError):
        ProviderAuthenticationEmailGateway(
            email_provider=FakeEmailProvider(fail=True)
        ).send_signup_otp(
            email="person@example.com",
            otp="123456",
            expires_at=datetime(2026, 9, 16, 12, 30, tzinfo=UTC),
        )


def test_signup_otp_email_sender_does_not_log_otp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        ProviderAuthenticationEmailGateway(
            email_provider=FakeEmailProvider()
        ).send_signup_otp(
            email="person@example.com",
            otp="123456",
            expires_at=datetime(2026, 9, 16, 12, 30, tzinfo=UTC),
        )

    assert "123456" not in caplog.text
