"""Shared security primitives for authentication OTP flows."""

from __future__ import annotations

import hmac
import re
import secrets
from hashlib import sha256

from nexus.domain.users import normalize_email
from nexus.errors import ErrorCode, NexusError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_auth_email(value: str) -> str:
    """Normalize and validate an email used by an authentication flow."""

    email = normalize_email(value)
    if len(email) > 320 or _EMAIL_RE.fullmatch(email) is None:
        raise NexusError(
            ErrorCode.VALIDATION_ERROR,
            "The request validation failed.",
            details={"field": "email"},
        )
    return email


def generate_numeric_otp(length: int) -> str:
    """Return a cryptographically random numeric OTP."""

    upper_bound = 10**length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def keyed_digest(*, secret: str, message: str) -> str:
    """Return a server-secret-bound digest for a non-reversible lookup key."""

    return hmac.new(secret.encode(), message.encode(), sha256).hexdigest()


def digest_otp(*, secret: str, email: str, purpose: str, otp: str) -> str:
    """Return a server-secret-bound digest for one OTP challenge."""

    return keyed_digest(secret=secret, message=f"{purpose}:{email}:{otp}")
