"""Role persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.infrastructure.persistence.base import Base

if TYPE_CHECKING:
    from nexus.infrastructure.persistence.models.organization import Organization
    from nexus.infrastructure.persistence.models.permission import Permission
    from nexus.infrastructure.persistence.models.role_permission import RolePermission


class Role(Base):
    """Organization-owned RBAC role."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_roles_organization_id_name"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, index=True, default=uuid.uuid4
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship(back_populates="roles")
    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permissions", back_populates="roles", viewonly=True
    )
