"""Authentication API composition root."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from nexus.application.authentication.email import (
    DefaultSignupOtpEmailSender,
    DefaultWelcomeEmailSender,
    SignupOtpEmailSender,
    WelcomeEmailSender,
)
from nexus.application.authentication.signup import SignupOtpService
from nexus.application.authentication.signup_verification import (
    SignupVerificationService,
)
from nexus.config.settings import settings
from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.mailer import EmailDeliveryError, EmailProvider
from nexus.infrastructure.mailer.providers import ResendEmailProvider
from nexus.infrastructure.persistence.repositories.administrator_role import (
    SqlAlchemyAdministratorRoleProvisioner,
)
from nexus.infrastructure.persistence.repositories.auth_session import (
    SqlAlchemyAuthSessionRepository,
)
from nexus.infrastructure.persistence.repositories.organization import (
    SqlAlchemyOrganizationRepository,
)
from nexus.infrastructure.persistence.repositories.otp_challenge import (
    SqlAlchemyOtpChallengeRepository,
)
from nexus.infrastructure.persistence.repositories.user import SqlAlchemyUserRepository
from nexus.infrastructure.persistence.repositories.user_role import (
    SqlAlchemyUserRoleRepository,
)
from nexus.infrastructure.persistence.session import get_db_session
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager
from nexus.infrastructure.rate_limit import RedisRateLimiter
from nexus.security.authentication_tokens import AccessTokenService
from nexus.services.authentication_session import AuthenticationSessionService
from nexus.services.otp import OtpVerificationService

RequestSession = Annotated[Session, Depends(get_db_session)]


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


def build_signup_otp_email_sender() -> SignupOtpEmailSender:
    return DefaultSignupOtpEmailSender(email_provider=build_email_provider())


def build_welcome_email_sender() -> WelcomeEmailSender:
    try:
        return DefaultWelcomeEmailSender(email_provider=build_email_provider())
    except EmailDeliveryError:
        return UnavailableWelcomeEmailSender()


def get_signup_otp_service(session: RequestSession) -> SignupOtpService:
    try:
        email_sender = build_signup_otp_email_sender()
    except EmailDeliveryError as exc:
        raise NexusError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "The service is temporarily unavailable.",
            retryable=True,
        ) from exc

    otp_challenge_repository = SqlAlchemyOtpChallengeRepository(session)
    return SignupOtpService(
        settings=settings,
        transaction=SqlAlchemyTransactionManager(session),
        user_repository=SqlAlchemyUserRepository(session),
        otp_challenge_repository=otp_challenge_repository,
        email_sender=email_sender,
        rate_limiter=RedisRateLimiter.from_url(settings.redis_url),
    )


def get_signup_verification_service(
    session: RequestSession,
) -> SignupVerificationService:
    otp_challenge_repository = SqlAlchemyOtpChallengeRepository(session)
    auth_session_repository = SqlAlchemyAuthSessionRepository(session)

    return SignupVerificationService(
        transaction=SqlAlchemyTransactionManager(session),
        user_repository=SqlAlchemyUserRepository(session),
        organization_repository=SqlAlchemyOrganizationRepository(session),
        user_role_repository=SqlAlchemyUserRoleRepository(session),
        administrator_role_provisioner=SqlAlchemyAdministratorRoleProvisioner(session),
        otp_verifier=OtpVerificationService(
            settings=settings,
            otp_challenge_repository=otp_challenge_repository,
        ),
        session_service=AuthenticationSessionService(
            access_token_service=AccessTokenService(
                secret=settings.auth_token_secret,
                expires_seconds=settings.access_token_expires_seconds,
                issuer=settings.auth_token_issuer,
            ),
            refresh_token_secret=settings.refresh_token_secret,
            refresh_token_expires_seconds=settings.refresh_token_expires_seconds,
            auth_session_repository=auth_session_repository,
        ),
        welcome_email_sender=build_welcome_email_sender(),
    )


SignupOtpServiceDep = Annotated[
    SignupOtpService,
    Depends(get_signup_otp_service),
]
SignupVerificationServiceDep = Annotated[
    SignupVerificationService,
    Depends(get_signup_verification_service),
]
