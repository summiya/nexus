"""Authentication API controller."""

from __future__ import annotations

from fastapi import APIRouter

from nexus.authentication.api.dependencies import SignupServiceDep
from nexus.authentication.api.schemas import (
    SignupRequestBody,
    SignupResponseBody,
    SignupVerificationRequestBody,
    SignupVerificationResponseBody,
)
from nexus.authentication.signup_service import (
    SignupOtpRequest,
    SignupVerificationRequest,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/signup", response_model=SignupResponseBody, status_code=202)
def request_signup_otp(
    body: SignupRequestBody,
    service: SignupServiceDep,
) -> SignupResponseBody:
    service.request_signup_otp(
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
    service: SignupServiceDep,
) -> SignupVerificationResponseBody:
    result = service.complete_signup(
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
