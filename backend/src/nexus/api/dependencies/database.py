"""FastAPI dependencies for application-owned database resources."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from nexus.api.dependencies import AppContainerDep
from nexus.infrastructure.persistence.session import Database


def get_database(container: AppContainerDep) -> Database:
    return container.database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_db_session(database: DatabaseDep) -> Iterator[Session]:
    """Yield one request-scoped session from the current application's database."""

    with database.session_factory() as session:
        yield session


RequestSession = Annotated[Session, Depends(get_db_session)]
