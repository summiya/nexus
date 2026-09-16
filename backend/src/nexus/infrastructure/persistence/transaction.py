"""SQLAlchemy transaction boundary adapter."""

from __future__ import annotations

from sqlalchemy.orm import Session


class SqlAlchemyTransactionManager:
    """Transaction manager backed by one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
