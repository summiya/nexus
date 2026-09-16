"""SQLAlchemy authentication session repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from nexus.infrastructure.persistence.models.auth_session import AuthSession
from nexus.infrastructure.persistence.models.user import User


class SqlAlchemyAuthSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, auth_session: AuthSession) -> None:
        self._session.add(auth_session)
        self._session.flush()

    def get_by_refresh_token_hash_for_update(
        self,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        return self._session.scalar(
            select(AuthSession)
            .options(joinedload(AuthSession.user).joinedload(User.organization))
            .where(AuthSession.refresh_token_hash == refresh_token_hash)
            .with_for_update(of=AuthSession)
        )
