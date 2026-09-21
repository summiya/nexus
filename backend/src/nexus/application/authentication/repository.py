"""Authentication persistence records and repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class OtpChallenge:
    """Application representation of a passwordless OTP challenge."""

    public_id: UUID
    email: str
    purpose: str
    code_digest: str
    expires_at: datetime
    max_attempts: int
    attempt_count: int = 0
    consumed_at: datetime | None = None
    locked_at: datetime | None = None


@dataclass(frozen=True)
class SignupAccount:
    """Organization administrator account created during signup."""

    organization_public_id: UUID
    organization_name: str
    organization_slug: str
    user_public_id: UUID
    email: str
    display_name: str
    email_verified_at: datetime


@dataclass(frozen=True)
class AuthenticationIdentity:
    """Public identity needed to create authenticated sessions."""

    user_public_id: UUID
    organization_public_id: UUID


@dataclass(frozen=True)
class AuthenticationSession:
    """Application representation of a durable refresh-token session."""

    public_id: UUID
    identity: AuthenticationIdentity
    refresh_token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class AuthenticationRepository(Protocol):
    """Persistence required by the current authentication use cases."""

    def user_exists_by_email(self, email: str) -> bool:
        """Return whether the normalized email is already registered."""

    def organization_exists_by_slug(self, slug: str) -> bool:
        """Return whether the normalized organization slug already exists."""

    def add_otp_challenge(self, challenge: OtpChallenge) -> None:
        """Stage and flush a new OTP challenge."""

    def get_latest_otp_challenge_for_update(
        self,
        *,
        email: str,
        purpose: str,
    ) -> OtpChallenge | None:
        """Return the latest matching OTP challenge, locked for update."""

    def update_otp_challenge(self, challenge: OtpChallenge) -> None:
        """Stage and flush changes to an OTP challenge."""

    def create_organization_administrator(
        self,
        account: SignupAccount,
    ) -> AuthenticationIdentity:
        """Stage and flush a new organization and its administrator."""

    def add_session(self, session: AuthenticationSession) -> None:
        """Stage and flush a durable authentication session."""

    def get_session_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthenticationSession | None:
        """Return the matching session and identity, locked for update."""

    def update_session(self, session: AuthenticationSession) -> None:
        """Stage and flush changes to a durable session."""
