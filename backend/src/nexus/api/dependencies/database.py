"""FastAPI dependencies for application-owned database resources."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from nexus.infrastructure.persistence.session import Database


def get_database(request: Request) -> Database:
    return request.app.state.database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_db_session(database: DatabaseDep) -> Iterator[Session]:
    """Yield one request-scoped session from the current application's database."""

    with database.session_factory() as session:
        yield session


RequestSession = Annotated[Session, Depends(get_db_session)]
