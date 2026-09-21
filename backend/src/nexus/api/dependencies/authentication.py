"""FastAPI dependencies for authentication application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from nexus.api.composition.authentication import AuthenticationComposition
from nexus.api.dependencies.database import RequestSession
from nexus.application.authentication.signup import SignupOtpService
from nexus.application.authentication.signup_verification import (
    SignupVerificationService,
)
from nexus.services.access_authentication import AccessAuthenticationService


def get_authentication_composition(request: Request) -> AuthenticationComposition:
    return request.app.state.authentication


AuthenticationCompositionDep = Annotated[
    AuthenticationComposition,
    Depends(get_authentication_composition),
]


def get_signup_otp_service(
    session: RequestSession,
    composition: AuthenticationCompositionDep,
) -> SignupOtpService:
    return composition.build_signup_otp_service(session)


def get_signup_verification_service(
    session: RequestSession,
    composition: AuthenticationCompositionDep,
) -> SignupVerificationService:
    return composition.build_signup_verification_service(session)


def get_access_authentication_service(
    composition: AuthenticationCompositionDep,
) -> AccessAuthenticationService:
    return composition.access_authentication_service


SignupOtpServiceDep = Annotated[
    SignupOtpService,
    Depends(get_signup_otp_service),
]
SignupVerificationServiceDep = Annotated[
    SignupVerificationService,
    Depends(get_signup_verification_service),
]
AccessAuthenticationServiceDep = Annotated[
    AccessAuthenticationService,
    Depends(get_access_authentication_service),
]
