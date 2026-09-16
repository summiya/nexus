"""User repository contracts."""

from __future__ import annotations

from typing import Protocol

from nexus.infrastructure.persistence.models.user import User


class UserRepository(Protocol):
    def exists_by_email(self, email: str) -> bool:
        """Return whether a user exists with the normalized email."""

    def add(self, user: User) -> None:
        """Persist a user and flush generated fields."""
