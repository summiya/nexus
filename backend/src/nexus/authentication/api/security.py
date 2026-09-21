"""Bearer authentication dependencies for protected API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nexus.authentication.api.dependencies import AccessAuthenticationServiceDep
from nexus.authentication.tokens import AuthTokenContext
from nexus.errors import ErrorCode, NexusError

bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


def get_current_auth_context(
    credentials: BearerCredentials,
    service: AccessAuthenticationServiceDep,
) -> AuthTokenContext:
    if credentials is None:
        raise NexusError(
            ErrorCode.UNAUTHORIZED,
            "Authentication credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return service.authenticate(credentials.credentials)


CurrentAuthContextDep = Annotated[
    AuthTokenContext,
    Depends(get_current_auth_context),
]
