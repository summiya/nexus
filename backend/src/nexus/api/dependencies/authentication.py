"""FastAPI dependencies for authentication application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from nexus.api.composition.authentication import AuthenticationComposition
from nexus.api.dependencies import AppContainerDep
from nexus.api.dependencies.database import RequestSession
from nexus.application.authentication.service import AuthenticationService
from nexus.services.access_authentication import AccessAuthenticationService


def get_authentication_composition(
    container: AppContainerDep,
) -> AuthenticationComposition:
    return container.authentication


AuthenticationCompositionDep = Annotated[
    AuthenticationComposition,
    Depends(get_authentication_composition),
]


def get_authentication_service(
    session: RequestSession,
    composition: AuthenticationCompositionDep,
) -> AuthenticationService:
    return composition.build_authentication_service(session)


def get_access_authentication_service(
    composition: AuthenticationCompositionDep,
) -> AccessAuthenticationService:
    return composition.access_authentication_service


AuthenticationServiceDep = Annotated[
    AuthenticationService,
    Depends(get_authentication_service),
]
AccessAuthenticationServiceDep = Annotated[
    AccessAuthenticationService,
    Depends(get_access_authentication_service),
]
