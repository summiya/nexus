"""Reusable outbound mail delivery utility."""

from .core import EmailDeliveryError, EmailMessage, EmailProvider

__all__ = ["EmailDeliveryError", "EmailMessage", "EmailProvider"]
