"""Generic outbound mail delivery contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    """Provider-agnostic outbound email message."""

    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailDeliveryError(Exception):
    """Raised when an email provider cannot deliver a message."""


class EmailProvider(Protocol):
    """Focused contract for outbound email delivery."""

    def send(self, message: EmailMessage) -> None:
        """Send one email message."""
