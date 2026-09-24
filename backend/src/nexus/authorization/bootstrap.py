"""Built-in RBAC role provisioning."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.domain.permissions import PERMISSION_CATALOG
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.permission import Permission
from nexus.infrastructure.persistence.models.role import Role
from nexus.infrastructure.persistence.models.role_permission import RolePermission

ADMINISTRATOR_ROLE_NAME = "Administrator"
ADMINISTRATOR_ROLE_DESCRIPTION = "Built-in organization administrator role"


async def provision_administrator_role(
    session: AsyncSession,
    organization_id: int,
) -> Role:
    """Provision the protected Administrator role for one organization.

    The caller owns the surrounding transaction. The organization row is locked so
    concurrent bootstrap attempts for the same organization are serialized. This
    function flushes generated state but never commits.
    """
    locked_organization_id = await session.scalar(
        select(Organization.id)
        .where(Organization.id == organization_id)
        .with_for_update()
    )
    if locked_organization_id is None:
        raise ValueError(f"Organization {organization_id} does not exist")

    role = await session.scalar(
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
        await session.flush()
    elif not role.is_system:
        raise ValueError(
            "Administrator role already exists for the organization but is not a system role"
        )

    permissions = list(
        await session.scalars(
            select(Permission).where(Permission.key.in_(PERMISSION_CATALOG))
        )
    )
    permission_by_key = {permission.key: permission for permission in permissions}
    missing_keys = set(PERMISSION_CATALOG) - permission_by_key.keys()
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise ValueError(f"Permission catalog is not seeded: {missing}")

    existing_permission_ids = set(
        await session.scalars(
            select(RolePermission.permission_id).where(
                RolePermission.role_id == role.id
            )
        )
    )
    for permission in permissions:
        if permission.id not in existing_permission_ids:
            session.add(RolePermission(role_id=role.id, permission_id=permission.id))

    await session.flush()
    return role
