"""SQLAlchemy implementation of the runtime permission-checking boundary."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.authorization import PermissionChecker, PermissionCheckError
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.permission import Permission
from nexus.infrastructure.persistence.models.role import Role
from nexus.infrastructure.persistence.models.role_permission import RolePermission
from nexus.infrastructure.persistence.models.user import User
from nexus.infrastructure.persistence.models.user_role import UserRole

_PERMISSION_CHECK_FAILURE_MESSAGE = "Permission check failed"


class SqlAlchemyPermissionChecker(PermissionChecker):
    """Check tenant-scoped permissions using one short-lived async session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def has_permission(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        permission_key: str,
    ) -> bool:
        permission_exists = (
            select(1)
            .select_from(Organization)
            .join(User, User.organization_id == Organization.id)
            .join(
                UserRole,
                and_(
                    UserRole.user_id == User.id,
                    UserRole.organization_id == Organization.id,
                ),
            )
            .join(
                Role,
                and_(
                    Role.id == UserRole.role_id,
                    Role.organization_id == Organization.id,
                ),
            )
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                Organization.public_id == organization_public_id,
                Organization.status == "active",
                Organization.deleted_at.is_(None),
                User.public_id == user_public_id,
                User.status == "active",
                User.deleted_at.is_(None),
                Role.deleted_at.is_(None),
                Permission.key == permission_key,
            )
            .exists()
        )

        try:
            async with self._session_factory() as session:
                return bool(await session.scalar(select(permission_exists)))
        except SQLAlchemyError as exc:
            raise PermissionCheckError(_PERMISSION_CHECK_FAILURE_MESSAGE) from exc


__all__ = ["SqlAlchemyPermissionChecker"]
