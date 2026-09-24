import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


@pytest.fixture
def authentication_async_engine(
    migrated_engine: Engine,
) -> Iterator[AsyncEngine]:
    async_engine = create_async_engine(migrated_engine.url, poolclass=NullPool)
    try:
        yield async_engine
    finally:
        asyncio.run(async_engine.dispose())


@pytest.fixture
def authentication_async_session_factory(
    authentication_async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=authentication_async_engine,
        autoflush=False,
        expire_on_commit=False,
    )
