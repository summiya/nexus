"""Authentication application composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from nexus.config.settings import Settings
from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage, EmailProvider
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
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager
from nexus.infrastructure.rate_limit import RateLimiter, RedisRateLimiter
from nexus.security.authentication_tokens import AccessTokenService
from nexus.services.access_authentication import AccessAuthenticationService
from nexus.services.authentication_session import AuthenticationSessionService
from nexus.services.otp import OtpVerificationService


def _noop() -> None:
    return None


@dataclass(frozen=True)
class UnavailableEmailProvider:
    """Fail safely when outbound email is intentionally disabled."""

    def send(self, message: EmailMessage) -> None:
        del message
        raise EmailDeliveryError("Email provider is not configured")


@dataclass(frozen=True)
class AuthenticationComposition:
    """Application-scoped authentication dependencies and request builders."""

    settings: Settings
    rate_limiter: RateLimiter
    signup_otp_email_sender: SignupOtpEmailSender
    welcome_email_sender: WelcomeEmailSender
    access_token_service: AccessTokenService
    access_authentication_service: AccessAuthenticationService
    close_callback: Callable[[], None] = _noop

    def build_signup_otp_service(self, session: Session) -> SignupOtpService:
        return SignupOtpService(
            settings=self.settings,
            transaction=SqlAlchemyTransactionManager(session),
            user_repository=SqlAlchemyUserRepository(session),
            otp_challenge_repository=SqlAlchemyOtpChallengeRepository(session),
            email_sender=self.signup_otp_email_sender,
            rate_limiter=self.rate_limiter,
        )

    def build_signup_verification_service(
        self,
        session: Session,
    ) -> SignupVerificationService:
        otp_challenge_repository = SqlAlchemyOtpChallengeRepository(session)
        auth_session_repository = SqlAlchemyAuthSessionRepository(session)
        return SignupVerificationService(
            transaction=SqlAlchemyTransactionManager(session),
            user_repository=SqlAlchemyUserRepository(session),
            organization_repository=SqlAlchemyOrganizationRepository(session),
            user_role_repository=SqlAlchemyUserRoleRepository(session),
            administrator_role_provisioner=SqlAlchemyAdministratorRoleProvisioner(
                session
            ),
            otp_verifier=OtpVerificationService(
                settings=self.settings,
                otp_challenge_repository=otp_challenge_repository,
            ),
            session_service=AuthenticationSessionService(
                access_token_service=self.access_token_service,
                refresh_token_secret=self.settings.refresh_token_secret,
                refresh_token_expires_seconds=(
                    self.settings.refresh_token_expires_seconds
                ),
                auth_session_repository=auth_session_repository,
            ),
            welcome_email_sender=self.welcome_email_sender,
        )

    def close(self) -> None:
        self.close_callback()


def build_email_provider(app_settings: Settings) -> EmailProvider:
    if app_settings.email_provider == "resend":
        if app_settings.resend_api_key is None:
            raise EmailDeliveryError("Resend API key is not configured")
        return ResendEmailProvider(
            api_key=app_settings.resend_api_key,
            from_address=app_settings.email_from_address,
        )
    if app_settings.email_provider == "disabled":
        return UnavailableEmailProvider()
    raise EmailDeliveryError("Unsupported email provider")


def build_authentication_composition(
    app_settings: Settings,
    *,
    rate_limiter: RateLimiter | None = None,
    email_provider: EmailProvider | None = None,
) -> AuthenticationComposition:
    """Build shared authentication resources from one settings instance."""

    resolved_rate_limiter = (
        rate_limiter
        if rate_limiter is not None
        else RedisRateLimiter.from_url(app_settings.redis_url)
    )
    resolved_email_provider = (
        email_provider
        if email_provider is not None
        else build_email_provider(app_settings)
    )
    access_token_service = AccessTokenService(
        secret=app_settings.auth_token_secret,
        expires_seconds=app_settings.access_token_expires_seconds,
        issuer=app_settings.auth_token_issuer,
    )
    close = getattr(resolved_rate_limiter, "close", None)
    close_callback = close if callable(close) else _noop
    return AuthenticationComposition(
        settings=app_settings,
        rate_limiter=resolved_rate_limiter,
        signup_otp_email_sender=DefaultSignupOtpEmailSender(
            email_provider=resolved_email_provider
        ),
        welcome_email_sender=DefaultWelcomeEmailSender(
            email_provider=resolved_email_provider
        ),
        access_token_service=access_token_service,
        access_authentication_service=AccessAuthenticationService(
            access_token_service=access_token_service
        ),
        close_callback=close_callback,
    )
