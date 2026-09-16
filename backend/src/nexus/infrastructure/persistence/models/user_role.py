"""User-role association persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.infrastructure.persistence.base import Base

if TYPE_CHECKING:
    from nexus.infrastructure.persistence.models.role import Role
    from nexus.infrastructure.persistence.models.user import User


class UserRole(Base):
    """Tenant-safe assignment of a role to a user."""

    __tablename__ = "user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_user_roles_user_organization_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["role_id", "organization_id"],
            ["roles.id", "roles.organization_id"],
            name="fk_user_roles_role_organization_roles",
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="user_roles", viewonly=True)
    role: Mapped[Role] = relationship(back_populates="user_roles", viewonly=True)
