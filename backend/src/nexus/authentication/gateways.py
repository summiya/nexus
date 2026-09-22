"""External capability contracts used by authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class AuthenticationEmailError(Exception):
    """Raised when an authentication email cannot be delivered."""


class AuthenticationEmailGateway(Protocol):
    """Send authentication emails without exposing a provider SDK."""

    def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        """Send a signup OTP."""

    def send_login_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        """Send a login OTP."""

    def send_welcome_email(self, *, email: str, display_name: str) -> None:
        """Send a post-signup welcome email."""


class RateLimitError(Exception):
    """Raised when the rate limiter cannot make a safe decision."""


class RateLimiter(Protocol):
    """Decide whether an authentication action is allowed."""

    def allow(self, *, key: str, limit: int, window_seconds: int) -> bool:
        """Return whether the key is allowed within the configured window."""


@dataclass(frozen=True)
class AccessTokenClaims:
    """Public identities encoded in an access token."""

    user_public_id: UUID
    organization_public_id: UUID
    session_public_id: UUID


class AccessTokenGatewayError(Exception):
    """Raised when an access token cannot be issued."""


class AccessTokenGateway(Protocol):
    """Issue access tokens without exposing JWT implementation details."""

    @property
    def expires_seconds(self) -> int:
        """Return the access-token lifetime."""

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        """Issue an access token for public authentication identities."""
