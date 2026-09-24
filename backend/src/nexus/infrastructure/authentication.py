"""Infrastructure adapters for authentication gateways."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from nexus.authentication.gateways import (
    AccessTokenClaims,
    AccessTokenGatewayError,
    AuthenticationEmailError,
)
from nexus.authentication.tokens import (
    AccessTokenError,
    AccessTokenService,
    AuthTokenContext,
)
from nexus.infrastructure.mailer import (
    EmailDeliveryError,
    EmailMessage,
    EmailProvider,
)


@dataclass(frozen=True)
class ProviderAuthenticationEmailGateway:
    """Compose authentication emails and delegate provider delivery."""

    email_provider: EmailProvider

    async def send_signup_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        await self._send(
            EmailMessage(
                to=email,
                subject="Your NEXUS signup code",
                text_body=(
                    "Use this code to continue signing up for NEXUS: "
                    f"{otp}\n\n"
                    f"This code expires at {expires_at.isoformat()}."
                ),
            )
        )

    async def send_login_otp(
        self,
        *,
        email: str,
        otp: str,
        expires_at: datetime,
    ) -> None:
        await self._send(
            EmailMessage(
                to=email,
                subject="Your NEXUS login code",
                text_body=(
                    "Use this code to sign in to NEXUS: "
                    f"{otp}\n\n"
                    f"This code expires at {expires_at.isoformat()}."
                ),
            )
        )

    async def send_welcome_email(self, *, email: str, display_name: str) -> None:
        await self._send(
            EmailMessage(
                to=email,
                subject="Welcome to NEXUS",
                text_body=f"Welcome to NEXUS, {display_name}.",
            )
        )

    async def _send(self, message: EmailMessage) -> None:
        try:
            await asyncio.to_thread(self.email_provider.send, message)
        except EmailDeliveryError as exc:
            raise AuthenticationEmailError("Email delivery failed") from exc


@dataclass(frozen=True)
class JwtAccessTokenGateway:
    """Adapt the Nexus JWT service to the application gateway."""

    token_service: AccessTokenService

    @property
    def expires_seconds(self) -> int:
        return self.token_service.expires_seconds

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        try:
            return self.token_service.issue_access_token(
                AuthTokenContext(
                    user_public_id=claims.user_public_id,
                    organization_public_id=claims.organization_public_id,
                    session_public_id=claims.session_public_id,
                )
            )
        except AccessTokenError as exc:
            raise AccessTokenGatewayError("Access-token issuance failed") from exc
