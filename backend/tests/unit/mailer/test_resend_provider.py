from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage
from nexus.infrastructure.mailer.providers import ResendEmailProvider


class FakeResendEmails:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.fail = False

    def send(self, payload: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("provider failed")
        self.payloads.append(payload)


def install_fake_resend(
    monkeypatch: pytest.MonkeyPatch,
    fake_emails: FakeResendEmails,
) -> SimpleNamespace:
    fake_resend = SimpleNamespace(api_key=None, Emails=fake_emails)
    monkeypatch.setitem(sys.modules, "resend", fake_resend)
    return fake_resend


def test_resend_provider_maps_email_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_emails = FakeResendEmails()
    fake_resend = install_fake_resend(monkeypatch, fake_emails)

    ResendEmailProvider(
        api_key="test-key",
        from_address="no-reply@example.com",
    ).send(
        EmailMessage(
            to="person@example.com",
            subject="Hello",
            text_body="Plain text",
            html_body="<p>HTML</p>",
        )
    )

    assert fake_resend.api_key == "test-key"
    assert fake_emails.payloads == [
        {
            "from": "no-reply@example.com",
            "to": "person@example.com",
            "subject": "Hello",
            "text": "Plain text",
            "html": "<p>HTML</p>",
        }
    ]


def test_resend_provider_omits_html_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_emails = FakeResendEmails()
    install_fake_resend(monkeypatch, fake_emails)

    ResendEmailProvider(
        api_key="test-key",
        from_address="no-reply@example.com",
    ).send(
        EmailMessage(
            to="person@example.com",
            subject="Hello",
            text_body="Plain text",
        )
    )

    assert "html" not in fake_emails.payloads[0]


def test_resend_provider_translates_vendor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_emails = FakeResendEmails()
    fake_emails.fail = True
    install_fake_resend(monkeypatch, fake_emails)

    with pytest.raises(EmailDeliveryError):
        ResendEmailProvider(
            api_key="test-key",
            from_address="no-reply@example.com",
        ).send(
            EmailMessage(
                to="person@example.com",
                subject="Hello",
                text_body="Plain text",
            )
        )
