"""Authentication session lifecycle."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from nexus.authentication.gateways import (
    AccessTokenClaims,
    AccessTokenGateway,
    AccessTokenGatewayError,
)
from nexus.authentication.repository import (
    AuthenticationIdentity,
    AuthenticationRepository,
    AuthenticationSession,
)
from nexus.errors import ErrorCode, NexusError
from nexus.ports.transaction import TransactionManager

_REFRESH_TOKEN_BYTES = 32
_TOKEN_TYPE = "bearer"


@dataclass(frozen=True)
class SessionPolicy:
    """Configuration values that directly control session behavior."""

    refresh_token_secret: str
    refresh_token_expires_seconds: int


@dataclass(frozen=True)
class SessionTokenResult:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class SessionService:
    """Create, rotate, and revoke durable authentication sessions."""

    policy: SessionPolicy
    transaction: TransactionManager
    repository: AuthenticationRepository
    access_token_gateway: AccessTokenGateway
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def create_session(
        self,
        *,
        identity: AuthenticationIdentity,
    ) -> SessionTokenResult:
        """Create a session and commit the current application transaction."""

        try:
            result = self._stage_session(identity)
            self.transaction.commit()
            return result
        except Exception:
            self.transaction.rollback()
            raise

    def refresh_session(self, *, refresh_token: str) -> SessionTokenResult:
        """Rotate a refresh token and commit its session update."""

        try:
            session = self._load_active_session(refresh_token)
            next_refresh_token = _generate_refresh_token()
            updated = replace(
                session,
                refresh_token_hash=self._hash_refresh_token(next_refresh_token),
                last_used_at=self.clock(),
            )
            self.repository.update_session(updated)
            access_token = self._issue_access_token(updated)
            self.transaction.commit()
            return SessionTokenResult(
                access_token=access_token,
                refresh_token=next_refresh_token,
                token_type=_TOKEN_TYPE,
                expires_in=self.access_token_gateway.expires_seconds,
            )
        except Exception:
            self.transaction.rollback()
            raise

    def revoke_session(self, *, refresh_token: str) -> None:
        """Revoke and commit a durable authentication session."""

        try:
            session = self._load_active_session(refresh_token)
            self.repository.update_session(replace(session, revoked_at=self.clock()))
            self.transaction.commit()
        except Exception:
            self.transaction.rollback()
            raise

    def _stage_session(
        self,
        identity: AuthenticationIdentity,
    ) -> SessionTokenResult:
        refresh_token = _generate_refresh_token()
        session = AuthenticationSession(
            public_id=uuid4(),
            identity=identity,
            refresh_token_hash=self._hash_refresh_token(refresh_token),
            expires_at=self.clock()
            + timedelta(seconds=self.policy.refresh_token_expires_seconds),
        )
        self.repository.add_session(session)
        return SessionTokenResult(
            access_token=self._issue_access_token(session),
            refresh_token=refresh_token,
            token_type=_TOKEN_TYPE,
            expires_in=self.access_token_gateway.expires_seconds,
        )

    def _load_active_session(self, refresh_token: str) -> AuthenticationSession:
        session = self.repository.get_session_by_refresh_token_hash_for_update(
            self._hash_refresh_token(refresh_token)
        )
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= self.clock()
        ):
            raise _invalid_credentials()
        return session

    def _issue_access_token(self, session: AuthenticationSession) -> str:
        try:
            return self.access_token_gateway.issue_access_token(
                AccessTokenClaims(
                    user_public_id=session.identity.user_public_id,
                    organization_public_id=session.identity.organization_public_id,
                    session_public_id=session.public_id,
                )
            )
        except AccessTokenGatewayError as exc:
            raise _service_unavailable() from exc

    def _hash_refresh_token(self, refresh_token: str) -> str:
        return hmac.new(
            self.policy.refresh_token_secret.encode(),
            refresh_token.encode(),
            sha256,
        ).hexdigest()


def _generate_refresh_token() -> str:
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def _invalid_credentials() -> NexusError:
    return NexusError(
        ErrorCode.UNAUTHORIZED,
        "Authentication credentials are invalid.",
    )


def _service_unavailable() -> NexusError:
    return NexusError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "The service is temporarily unavailable.",
        retryable=True,
    )
