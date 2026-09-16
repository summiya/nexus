"""OTP generation and digest helpers."""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256


def generate_numeric_otp(length: int) -> str:
    """Return a cryptographically random numeric OTP."""
    upper_bound = 10**length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def digest_otp(*, secret: str, email: str, purpose: str, otp: str) -> str:
    """Return a server-secret-bound digest for one OTP challenge."""
    message = f"{purpose}:{email}:{otp}".encode()
    return hmac.new(secret.encode(), message, sha256).hexdigest()
