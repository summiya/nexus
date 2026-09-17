"""Reusable bearer access-token authentication service."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.errors import ErrorCode, NexusError
from nexus.security.authentication_tokens import (
    AccessTokenError,
    AccessTokenExpiredError,
    AccessTokenService,
    AuthTokenContext,
)

_BEARER_HEADERS = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class AccessAuthenticationService:
    """Authenticate a bearer access token into trusted request context."""

    access_token_service: AccessTokenService

    def authenticate(self, access_token: str) -> AuthTokenContext:
        try:
            return self.access_token_service.verify_access_token(access_token)
        except AccessTokenExpiredError as exc:
            raise NexusError(
                ErrorCode.ACCESS_TOKEN_EXPIRED,
                "Access token has expired.",
                headers=_BEARER_HEADERS,
            ) from exc
        except AccessTokenError as exc:
            raise NexusError(
                ErrorCode.ACCESS_TOKEN_INVALID,
                "Access token is invalid.",
                headers=_BEARER_HEADERS,
            ) from exc
