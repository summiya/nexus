"""Resend outbound mail provider adapter."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from ..core import EmailDeliveryError, EmailMessage


@dataclass(frozen=True)
class ResendEmailProvider:
    """Send generic email messages through Resend."""

    api_key: str
    from_address: str

    def send(self, message: EmailMessage) -> None:
        resend = _load_resend_sdk()
        payload: dict[str, Any] = {
            "from": self.from_address,
            "to": message.to,
            "subject": message.subject,
            "text": message.text_body,
        }
        if message.html_body is not None:
            payload["html"] = message.html_body

        try:
            resend.api_key = self.api_key
            resend.Emails.send(payload)
        except Exception as exc:
            raise EmailDeliveryError(
                "Email provider failed to deliver message"
            ) from exc


def _load_resend_sdk() -> Any:
    try:
        return importlib.import_module("resend")
    except ModuleNotFoundError as exc:
        raise EmailDeliveryError("Resend SDK is not installed") from exc
