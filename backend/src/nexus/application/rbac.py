"""RBAC application services."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.domain.permissions import PERMISSION_CATALOG
from nexus.infrastructure.persistence.models.permission import Permission
from nexus.infrastructure.persistence.models.role import Role
from nexus.infrastructure.persistence.models.role_permission import RolePermission

ADMINISTRATOR_ROLE_NAME = "Administrator"
ADMINISTRATOR_ROLE_DESCRIPTION = "Built-in organization administrator role"


def provision_administrator_role(session: Session, organization_id: int) -> Role:
    """Provision the protected Administrator role for an organization.

    The caller owns the surrounding transaction. This function flushes changes so
    generated identifiers are available, but deliberately does not commit.
    Repeated calls in the same or later transaction reuse the existing role and
    role-permission mappings.
    """
    role = session.scalar(
        select(Role).where(
            Role.organization_id == organization_id,
            Role.name == ADMINISTRATOR_ROLE_NAME,
        )
    )

    if role is None:
        role = Role(
            organization_id=organization_id,
            name=ADMINISTRATOR_ROLE_NAME,
            description=ADMINISTRATOR_ROLE_DESCRIPTION,
            is_system=True,
        )
        session.add(role)
        session.flush()
    elif not role.is_system:
        raise ValueError(
            "Administrator role already exists for the organization but is not a system role"
        )

    permissions = list(
        session.scalars(
            select(Permission).where(Permission.key.in_(PERMISSION_CATALOG))
        )
    )
    permission_by_key = {permission.key: permission for permission in permissions}
    missing_keys = set(PERMISSION_CATALOG) - permission_by_key.keys()
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise ValueError(f"Permission catalog is not seeded: {missing}")

    existing_permission_ids = set(
        session.scalars(
            select(RolePermission.permission_id).where(
                RolePermission.role_id == role.id
            )
        )
    )
    for permission in permissions:
        if permission.id not in existing_permission_ids:
            session.add(RolePermission(role_id=role.id, permission_id=permission.id))

    session.flush()
    return role
