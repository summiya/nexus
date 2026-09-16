"""User persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from nexus.domain.users import normalize_email
from nexus.infrastructure.persistence.base import Base

if TYPE_CHECKING:
    from nexus.infrastructure.persistence.models.organization_membership import (
        OrganizationMembership,
    )


class User(Base):
    """Persisted NEXUS user identity/profile record."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, index=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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

    organization_membership: Mapped[OrganizationMembership | None] = relationship(
        back_populates="user",
        foreign_keys="OrganizationMembership.user_id",
        uselist=False,
    )
    invited_organization_memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="inviter",
        foreign_keys="OrganizationMembership.invited_by",
    )

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        return normalize_email(value)
