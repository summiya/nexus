"""SQLAlchemy user repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.infrastructure.persistence.models.user import User


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def exists_by_email(self, email: str) -> bool:
        return (
            self._session.scalar(select(User.id).where(User.email == email)) is not None
        )

    def add(self, user: User) -> None:
        self._session.add(user)
        self._session.flush()
