"""Authentication session repository contracts."""

from __future__ import annotations

from typing import Protocol

from nexus.infrastructure.persistence.models.auth_session import AuthSession


class AuthSessionRepository(Protocol):
    def add(self, auth_session: AuthSession) -> None:
        """Persist an authentication session and flush generated fields."""

    def get_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        """Return an authentication session by refresh-token hash, locked for update."""
