"""Resend outbound mail provider adapter."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from ..core import EmailDeliveryError, EmailMessage

type _ResendPayload = dict[str, object]
type _DeliveryErrors = tuple[type[BaseException], ...]


@dataclass(frozen=True)
class ResendEmailProvider:
    """Send generic email messages through Resend."""

    api_key: str
    from_address: str

    def send(self, message: EmailMessage) -> None:
        payload: _ResendPayload = {
            "from": self.from_address,
            "to": message.to,
            "subject": message.subject,
            "text": message.text_body,
        }
        if message.html_body is not None:
            payload["html"] = message.html_body

        _ResendClient(api_key=self.api_key).send(payload)


@dataclass(frozen=True)
class _ResendSdk:
    module: Any
    delivery_errors: _DeliveryErrors


@dataclass(frozen=True)
class _ResendClient:
    api_key: str

    def send(self, payload: _ResendPayload) -> None:
        sdk = _load_resend_sdk()
        try:
            sdk.module.api_key = self.api_key
            sdk.module.Emails.send(payload)
        except sdk.delivery_errors as exc:
            raise EmailDeliveryError(
                "Email provider failed to deliver message"
            ) from exc


def _load_resend_sdk() -> _ResendSdk:
    try:
        resend = importlib.import_module("resend")
        resend_exceptions = importlib.import_module("resend.exceptions")
    except ModuleNotFoundError as exc:
        raise EmailDeliveryError("Resend SDK is not installed") from exc

    return _ResendSdk(
        module=resend,
        delivery_errors=(
            resend_exceptions.ResendError,
            resend_exceptions.NoContentError,
        ),
    )
