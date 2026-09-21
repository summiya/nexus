"""FastAPI dependencies for authentication application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from nexus.api.composition.authentication import AuthenticationComposition
from nexus.api.dependencies import AppContainerDep
from nexus.api.dependencies.database import RequestSession
from nexus.application.authentication.service import SessionService, SignupService
from nexus.services.access_authentication import AccessAuthenticationService


def get_authentication_composition(
    container: AppContainerDep,
) -> AuthenticationComposition:
    return container.authentication


AuthenticationCompositionDep = Annotated[
    AuthenticationComposition,
    Depends(get_authentication_composition),
]


def get_signup_service(
    session: RequestSession,
    composition: AuthenticationCompositionDep,
) -> SignupService:
    return composition.build_signup_service(session)


def get_session_service(
    session: RequestSession,
    composition: AuthenticationCompositionDep,
) -> SessionService:
    return composition.build_session_service(session)


def get_access_authentication_service(
    composition: AuthenticationCompositionDep,
) -> AccessAuthenticationService:
    return composition.access_authentication_service


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
