"""Authentication application composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from nexus.authentication.gateways import (
    AccessTokenGateway,
    AuthenticationEmailGateway,
    RateLimiter,
)
from nexus.authentication.login_service import LoginPolicy, LoginService
from nexus.authentication.session_service import SessionPolicy, SessionService
from nexus.authentication.signup_service import SignupPolicy, SignupService
from nexus.authentication.tokens import (
    AccessAuthenticationService,
    AccessTokenService,
)
from nexus.config.settings import Settings
from nexus.infrastructure.authentication import (
    JwtAccessTokenGateway,
    ProviderAuthenticationEmailGateway,
)
from nexus.infrastructure.mailer import EmailDeliveryError, EmailMessage, EmailProvider
from nexus.infrastructure.mailer.providers import ResendEmailProvider
from nexus.infrastructure.persistence.repositories.authentication import (
    SqlAlchemyAuthenticationRepository,
)
from nexus.infrastructure.persistence.transaction import SqlAlchemyTransactionManager
from nexus.infrastructure.rate_limit import RedisRateLimiter


def _noop() -> None:
    return None


def _resolve_close_callback(resource: object) -> Callable[[], None]:
    close = getattr(resource, "close", None)
    if not callable(close):
        return _noop
    return cast(Callable[[], None], close)


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
    email_gateway: AuthenticationEmailGateway
    access_token_gateway: AccessTokenGateway
    access_token_service: AccessTokenService
    access_authentication_service: AccessAuthenticationService
    close_callback: Callable[[], None] = _noop

    def build_login_service(self, session: Session) -> LoginService:
        return LoginService(
            policy=LoginPolicy(
                otp_hmac_secret=self.settings.otp_hmac_secret,
                otp_length=self.settings.signup_otp_length,
                otp_ttl_seconds=self.settings.signup_otp_ttl_seconds,
                otp_max_attempts=self.settings.signup_otp_max_attempts,
                otp_rate_limit_max_requests=(
                    self.settings.signup_otp_rate_limit_max_requests
                ),
                otp_rate_limit_window_seconds=(
                    self.settings.signup_otp_rate_limit_window_seconds
                ),
            ),
            transaction=SqlAlchemyTransactionManager(session),
            repository=SqlAlchemyAuthenticationRepository(session),
            email_gateway=self.email_gateway,
            rate_limiter=self.rate_limiter,
        )

    def build_signup_service(self, session: Session) -> SignupService:
        transaction = SqlAlchemyTransactionManager(session)
        repository = SqlAlchemyAuthenticationRepository(session)
        session_service = SessionService(
            policy=SessionPolicy(
                refresh_token_secret=self.settings.refresh_token_secret,
                refresh_token_expires_seconds=(
                    self.settings.refresh_token_expires_seconds
                ),
            ),
            transaction=transaction,
            repository=repository,
            access_token_gateway=self.access_token_gateway,
        )
        return SignupService(
            policy=SignupPolicy(
                otp_hmac_secret=self.settings.otp_hmac_secret,
                signup_otp_length=self.settings.signup_otp_length,
                signup_otp_ttl_seconds=self.settings.signup_otp_ttl_seconds,
                signup_otp_max_attempts=self.settings.signup_otp_max_attempts,
                signup_otp_rate_limit_max_requests=(
                    self.settings.signup_otp_rate_limit_max_requests
                ),
                signup_otp_rate_limit_window_seconds=(
                    self.settings.signup_otp_rate_limit_window_seconds
                ),
            ),
            transaction=transaction,
            repository=repository,
            session_service=session_service,
            email_gateway=self.email_gateway,
            rate_limiter=self.rate_limiter,
        )

    def build_session_service(self, session: Session) -> SessionService:
        return SessionService(
            policy=SessionPolicy(
                refresh_token_secret=self.settings.refresh_token_secret,
                refresh_token_expires_seconds=(
                    self.settings.refresh_token_expires_seconds
                ),
            ),
            transaction=SqlAlchemyTransactionManager(session),
            repository=SqlAlchemyAuthenticationRepository(session),
            access_token_gateway=self.access_token_gateway,
        )

    def close(self) -> None:
        self.close_callback()


def build_email_provider(app_settings: Settings) -> EmailProvider:
    if app_settings.email_provider == "resend":
        if not app_settings.resend_api_key:
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

    resolved_email_provider = (
        email_provider
        if email_provider is not None
        else build_email_provider(app_settings)
    )
    resolved_rate_limiter = (
        rate_limiter
        if rate_limiter is not None
        else RedisRateLimiter.from_url(app_settings.redis_url)
    )
    access_token_service = AccessTokenService(
        secret=app_settings.auth_token_secret,
        expires_seconds=app_settings.access_token_expires_seconds,
        issuer=app_settings.auth_token_issuer,
    )
    email_gateway = ProviderAuthenticationEmailGateway(resolved_email_provider)
    return AuthenticationComposition(
        settings=app_settings,
        rate_limiter=resolved_rate_limiter,
        email_gateway=email_gateway,
        access_token_gateway=JwtAccessTokenGateway(access_token_service),
        access_token_service=access_token_service,
        access_authentication_service=AccessAuthenticationService(
            access_token_service=access_token_service
        ),
        close_callback=_resolve_close_callback(resolved_rate_limiter),
    )
