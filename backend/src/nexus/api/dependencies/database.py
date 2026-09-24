"""FastAPI dependencies for application-owned database resources."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.dependencies import AppContainerDep
from nexus.infrastructure.persistence.session import Database


def get_database(container: AppContainerDep) -> Database:
    return container.database


DatabaseDep = Annotated[Database, Depends(get_database)]


async def get_db_session(database: DatabaseDep) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session from the application database."""

    async with database.session_factory() as session:
        yield session


RequestSession = Annotated[AsyncSession, Depends(get_db_session)]
