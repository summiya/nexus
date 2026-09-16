"""User-role assignment repository contracts."""

from __future__ import annotations

from typing import Protocol

from nexus.infrastructure.persistence.models.user_role import UserRole


class UserRoleRepository(Protocol):
    def add(self, user_role: UserRole) -> None:
        """Persist a user-role assignment and flush generated fields."""
