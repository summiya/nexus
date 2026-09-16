"""Organization repository contracts."""

from __future__ import annotations

from typing import Protocol

from nexus.infrastructure.persistence.models.organization import Organization


class OrganizationRepository(Protocol):
    def exists_by_slug(self, slug: str) -> bool:
        """Return whether an organization exists with the normalized slug."""

    def add(self, organization: Organization) -> None:
        """Persist an organization and flush generated fields."""
