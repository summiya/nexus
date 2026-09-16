"""Authorization service contracts consumed by application use cases."""

from __future__ import annotations

from typing import Protocol

from nexus.infrastructure.persistence.models.role import Role


class AdministratorRoleProvisioner(Protocol):
    def provision_for_organization(self, organization_id: int) -> Role:
        """Provision and return the Administrator role for an organization."""
