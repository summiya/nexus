"""Access-token security helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from nexus.errors import ErrorCode, NexusError

_BEARER_HEADERS = {"WWW-Authenticate": "Bearer"}


class AccessTokenError(Exception):
    """Raised when an access token cannot be issued or verified."""


class AccessTokenExpiredError(AccessTokenError):
    """Raised when an access token is expired."""


@dataclass(frozen=True)
class AuthTokenContext:
    """Trusted authentication context encoded into an access token."""

    user_public_id: UUID
    organization_public_id: UUID
    session_public_id: UUID


@dataclass(frozen=True)
class AccessTokenService:
    """Issue and verify stateless short-lived access tokens."""

    secret: str
    expires_seconds: int
    issuer: str | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def issue_access_token(self, context: AuthTokenContext) -> str:
        issued_at = self.clock()
        expires_at = issued_at + timedelta(seconds=self.expires_seconds)
        claims: dict[str, Any] = {
            "sub": str(context.user_public_id),
            "org": str(context.organization_public_id),
            "sid": str(context.session_public_id),
            "typ": "access",
            "iat": issued_at,
            "exp": expires_at,
        }
        if self.issuer is not None:
            claims["iss"] = self.issuer

        return jwt.encode(claims, self.secret, algorithm="HS256")

    def verify_access_token(self, token: str) -> AuthTokenContext:
        try:
            decode_kwargs: dict[str, Any] = {
                "algorithms": ["HS256"],
                "options": {
                    "require": ["sub", "org", "sid", "typ", "iat", "exp"],
                },
            }
            if self.issuer is not None:
                decode_kwargs["issuer"] = self.issuer

            claims = jwt.decode(token, self.secret, **decode_kwargs)
            if claims["typ"] != "access":
                raise AccessTokenError("Unexpected token type")
            return AuthTokenContext(
                user_public_id=UUID(claims["sub"]),
                organization_public_id=UUID(claims["org"]),
                session_public_id=UUID(claims["sid"]),
            )
        except jwt.ExpiredSignatureError as exc:
            raise AccessTokenExpiredError("Access token is expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AccessTokenError("Access token is invalid") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise AccessTokenError("Access token claims are invalid") from exc


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
