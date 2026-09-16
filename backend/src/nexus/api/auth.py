"""Authentication API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from nexus.application.authentication.email import (
    DefaultSignupOtpEmailSender,
    DefaultWelcomeEmailSender,
    WelcomeEmailSender,
)
from nexus.application.authentication.otp_verification import OtpVerificationService
from nexus.application.authentication.session import AuthenticationSessionService
from nexus.application.authentication.signup import (
    SignupOtpRequest,
    SignupOtpService,
)
from nexus.application.authentication.signup_verification import (
    SignupVerificationRequest,
    SignupVerificationService,
)
from nexus.config.settings import settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.mailer import EmailDeliveryError, EmailProvider
from nexus.infrastructure.mailer.providers import ResendEmailProvider
from nexus.infrastructure.persistence.session import get_db_session
from nexus.infrastructure.rate_limit import RedisRateLimiter
from nexus.security.authentication_tokens import AccessTokenService

router = APIRouter(prefix="/auth", tags=["authentication"])


class SignupRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)


class SignupResponseBody(BaseModel):
    status: str


class SignupVerificationRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    otp: str = Field(min_length=1, max_length=10)
    organization_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class SignupVerificationResponseBody(BaseModel):
    status: str
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class UnavailableWelcomeEmailSender:
    def send_welcome_email(self, *, email: str, display_name: str) -> None:
        del email, display_name
        raise EmailDeliveryError("Email provider is not configured")


def build_email_provider() -> EmailProvider:
    if settings.email_provider == "resend":
        if settings.resend_api_key is None:
            raise EmailDeliveryError("Resend API key is not configured")
        return ResendEmailProvider(
            api_key=settings.resend_api_key,
            from_address=settings.email_from_address,
        )
    if settings.email_provider == "disabled":
        raise EmailDeliveryError("Email provider is not configured")
    raise EmailDeliveryError("Unsupported email provider")


def get_signup_otp_service() -> SignupOtpService:
    try:
        email_provider = build_email_provider()
    except EmailDeliveryError as exc:
        raise NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "The service is temporarily unavailable.",
            retryable=True,
        ) from exc

    return SignupOtpService(
        settings=settings,
        email_sender=DefaultSignupOtpEmailSender(email_provider=email_provider),
        rate_limiter=RedisRateLimiter.from_url(settings.redis_url),
    )


def get_signup_verification_service() -> SignupVerificationService:
    try:
        welcome_email_sender: WelcomeEmailSender = DefaultWelcomeEmailSender(
            email_provider=build_email_provider()
        )
    except EmailDeliveryError:
        welcome_email_sender = UnavailableWelcomeEmailSender()

    return SignupVerificationService(
        otp_verifier=OtpVerificationService(settings=settings),
        session_service=AuthenticationSessionService(
            access_token_service=AccessTokenService(
                secret=settings.auth_token_secret,
                expires_seconds=settings.access_token_expires_seconds,
                issuer=settings.auth_token_issuer,
            ),
            refresh_token_secret=settings.refresh_token_secret,
            refresh_token_expires_seconds=settings.refresh_token_expires_seconds,
        ),
        welcome_email_sender=welcome_email_sender,
    )


@router.post("/signup", response_model=SignupResponseBody, status_code=202)
def request_signup_otp(
    body: SignupRequestBody,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[SignupOtpService, Depends(get_signup_otp_service)],
) -> SignupResponseBody:
    service.request_signup_otp(
        session=session,
        request=SignupOtpRequest(
            organization_name=body.organization_name,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
        ),
    )
    return SignupResponseBody(status="accepted")


@router.post("/signup/verify", response_model=SignupVerificationResponseBody)
def verify_signup(
    body: SignupVerificationRequestBody,
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[
        SignupVerificationService,
        Depends(get_signup_verification_service),
    ],
) -> SignupVerificationResponseBody:
    result = service.complete_signup(
        session=session,
        request=SignupVerificationRequest(
            email=body.email,
            otp=body.otp,
            organization_name=body.organization_name,
            first_name=body.first_name,
            last_name=body.last_name,
        ),
    )
    return SignupVerificationResponseBody(
        status=result.status,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
    )
