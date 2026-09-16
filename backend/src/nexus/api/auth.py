"""Authentication API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from nexus.application.authentication.signup import (
    SignupOtpRequest,
    SignupOtpService,
)
from nexus.config.settings import settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.email import (
    EmailDeliveryError,
    build_signup_otp_email_provider,
)
from nexus.infrastructure.persistence.session import get_db_session
from nexus.infrastructure.rate_limit import RedisRateLimiter

router = APIRouter(prefix="/auth", tags=["authentication"])


class SignupRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)


class SignupResponseBody(BaseModel):
    status: str


def get_signup_otp_service() -> SignupOtpService:
    try:
        email_provider = build_signup_otp_email_provider(
            provider_name=settings.email_provider,
            from_address=settings.email_from_address,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_username=settings.smtp_username,
            smtp_password=settings.smtp_password,
            smtp_security=settings.smtp_security,
        )
    except EmailDeliveryError as exc:
        raise NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "The service is temporarily unavailable.",
            retryable=True,
        ) from exc

    return SignupOtpService(
        settings=settings,
        email_provider=email_provider,
        rate_limiter=RedisRateLimiter.from_url(settings.redis_url),
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
