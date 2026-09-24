"""FastAPI dependencies for authentication application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.api.dependencies.database import RequestSession
from nexus.authentication.login_service import LoginService
from nexus.authentication.session_service import SessionService
from nexus.authentication.signup_service import SignupService
from nexus.authentication.tokens import AccessAuthenticationService


async def get_login_service(
    session: RequestSession,
    container: AppContainerDep,
) -> LoginService:
    return container.authentication.build_login_service(session)


async def get_signup_service(
    session: RequestSession,
    container: AppContainerDep,
) -> SignupService:
    return container.authentication.build_signup_service(session)


async def get_session_service(
    session: RequestSession,
    container: AppContainerDep,
) -> SessionService:
    return container.authentication.build_session_service(session)


def get_access_authentication_service(
    container: AppContainerDep,
) -> AccessAuthenticationService:
    return container.authentication.access_authentication_service


LoginServiceDep = Annotated[
    LoginService,
    Depends(get_login_service),
]
SignupServiceDep = Annotated[
    SignupService,
    Depends(get_signup_service),
]
SessionServiceDep = Annotated[
    SessionService,
    Depends(get_session_service),
]
AccessAuthenticationServiceDep = Annotated[
    AccessAuthenticationService,
    Depends(get_access_authentication_service),
]
