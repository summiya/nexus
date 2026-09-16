"""Authentication session orchestration."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.errors import ErrorCode, NexusError
from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.user import User
from nexus.security.authentication_tokens import (
    AccessTokenError,
    AccessTokenService,
    AuthTokenContext,
)

_TOKEN_TYPE = "bearer"
_REFRESH_TOKEN_BYTES = 32


@dataclass(frozen=True)
class SessionTokenResult:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class AuthenticationSessionService:
    """Create, rotate, and revoke durable refresh-token sessions."""

    access_token_service: AccessTokenService
    refresh_token_secret: str
    refresh_token_expires_seconds: int
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def create_session(self, session: Session, *, user: User) -> SessionTokenResult:
        refresh_token = _generate_refresh_token()
        auth_session = AuthSession(
            user_id=user.id,
            refresh_token_hash=self._hash_refresh_token(refresh_token),
            expires_at=self.clock()
            + timedelta(seconds=self.refresh_token_expires_seconds),
        )
        session.add(auth_session)
        session.flush()

        access_token = self._issue_access_token(user=user, auth_session=auth_session)
        return SessionTokenResult(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=_TOKEN_TYPE,
            expires_in=self.access_token_service.expires_seconds,
        )

    def refresh_session(
        self,
        session: Session,
        *,
        refresh_token: str,
    ) -> SessionTokenResult:
        auth_session = self._load_active_session_for_update(
            session=session,
            refresh_token=refresh_token,
        )

        next_refresh_token = _generate_refresh_token()
        auth_session.refresh_token_hash = self._hash_refresh_token(next_refresh_token)
        auth_session.last_used_at = self.clock()
        session.flush()

        access_token = self._issue_access_token(
            user=auth_session.user,
            auth_session=auth_session,
        )
        return SessionTokenResult(
            access_token=access_token,
            refresh_token=next_refresh_token,
            token_type=_TOKEN_TYPE,
            expires_in=self.access_token_service.expires_seconds,
        )

    def revoke_session(self, session: Session, *, refresh_token: str) -> None:
        auth_session = self._load_active_session_for_update(
            session=session,
            refresh_token=refresh_token,
        )
        auth_session.revoked_at = self.clock()
        session.flush()

    def _load_active_session_for_update(
        self,
        *,
        session: Session,
        refresh_token: str,
    ) -> AuthSession:
        auth_session = session.scalar(
            select(AuthSession)
            .where(
                AuthSession.refresh_token_hash
                == self._hash_refresh_token(refresh_token)
            )
            .with_for_update()
        )
        now = self.clock()
        if (
            auth_session is None
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= now
        ):
            raise NexusError(
                ErrorCode.UNAUTHORIZED,
                "Authentication credentials are invalid.",
            )
        return auth_session

    def _issue_access_token(
        self,
        *,
        user: User,
        auth_session: AuthSession,
    ) -> str:
        try:
            return self.access_token_service.issue_access_token(
                AuthTokenContext(
                    user_public_id=user.public_id,
                    organization_public_id=user.organization.public_id,
                    session_public_id=auth_session.public_id,
                )
            )
        except AccessTokenError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The service is temporarily unavailable.",
                retryable=True,
            ) from exc

    def _hash_refresh_token(self, refresh_token: str) -> str:
        return hmac.new(
            self.refresh_token_secret.encode(),
            refresh_token.encode(),
            sha256,
        ).hexdigest()


def _generate_refresh_token() -> str:
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
