"""OTP generation and digest helpers."""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256


def generate_numeric_otp(length: int) -> str:
    """Return a cryptographically random numeric OTP."""
    upper_bound = 10**length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def keyed_digest(*, secret: str, message: str) -> str:
    """Return a server-secret-bound digest for non-reversible lookup keys."""
    return hmac.new(secret.encode(), message.encode(), sha256).hexdigest()


def digest_otp(*, secret: str, email: str, purpose: str, otp: str) -> str:
    """Return a server-secret-bound digest for one OTP challenge."""
    return keyed_digest(secret=secret, message=f"{purpose}:{email}:{otp}")
