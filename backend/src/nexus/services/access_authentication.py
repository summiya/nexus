"""Reusable bearer access-token authentication service."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.errors import ErrorCode, NexusError
from nexus.security.authentication_tokens import (
    AccessTokenError,
    AccessTokenService,
    AuthTokenContext,
)


@dataclass(frozen=True)
class AccessAuthenticationService:
    """Authenticate a bearer access token into trusted request context."""

    access_token_service: AccessTokenService

    def authenticate(self, access_token: str) -> AuthTokenContext:
        try:
            return self.access_token_service.verify_access_token(access_token)
        except AccessTokenError as exc:
            raise NexusError(
                ErrorCode.UNAUTHORIZED,
                "Authentication credentials are invalid.",
            ) from exc
