"""SQLAlchemy user-role assignment repository."""

from __future__ import annotations

from sqlalchemy.orm import Session

from nexus.infrastructure.persistence.models.user_role import UserRole


class SqlAlchemyUserRoleRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user_role: UserRole) -> None:
        self._session.add(user_role)
        self._session.flush()
