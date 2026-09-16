"""SQLAlchemy-backed authorization provisioner adapter."""

from __future__ import annotations

from sqlalchemy.orm import Session

from nexus.authorization.bootstrap import provision_administrator_role
from nexus.infrastructure.persistence.models.role import Role


class SqlAlchemyAdministratorRoleProvisioner:
    def __init__(self, session: Session) -> None:
        self._session = session

    def provision_for_organization(self, organization_id: int) -> Role:
        return provision_administrator_role(self._session, organization_id)
