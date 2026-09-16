"""Bearer authentication dependencies for protected API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nexus.config.settings import settings
from nexus.security.authentication_tokens import AccessTokenService, AuthTokenContext
from nexus.services.access_authentication import AccessAuthenticationService

bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


def get_access_authentication_service() -> AccessAuthenticationService:
    return AccessAuthenticationService(
        access_token_service=AccessTokenService(
            secret=settings.auth_token_secret,
            expires_seconds=settings.access_token_expires_seconds,
            issuer=settings.auth_token_issuer,
        )
    )


AccessAuthenticationServiceDep = Annotated[
    AccessAuthenticationService,
    Depends(get_access_authentication_service),
]


def get_current_auth_context(
    credentials: BearerCredentials,
    service: AccessAuthenticationServiceDep,
) -> AuthTokenContext:
    if credentials is None:
        from nexus.errors import ErrorCode, NexusError

        raise NexusError(
            ErrorCode.UNAUTHORIZED,
            "Authentication credentials are required.",
        )
    return service.authenticate(credentials.credentials)


CurrentAuthContextDep = Annotated[
    AuthTokenContext,
    Depends(get_current_auth_context),
]
