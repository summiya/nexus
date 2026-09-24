import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nexus.api.dependencies.database import get_db_session
from nexus.infrastructure.persistence.session import Database, build_database

DATABASE_URL = "postgresql://test:secret@localhost:5432/nexus_test"


def test_build_database_creates_one_async_postgresql_resource() -> None:
    database = build_database(DATABASE_URL)

    try:
        assert isinstance(database.engine, AsyncEngine)
        assert database.engine.url.drivername == "postgresql+psycopg"
        assert database.engine.url.database == "nexus_test"
        assert not hasattr(database, "async_engine")
        assert not hasattr(database, "async_session_factory")
    finally:
        asyncio.run(database.dispose())


def test_explicit_psycopg_url_remains_supported() -> None:
    database = build_database(
        "postgresql+psycopg://test:secret@localhost:5432/nexus_test"
    )

    try:
        assert database.engine.url.drivername == "postgresql+psycopg"
    finally:
        asyncio.run(database.dispose())


def test_session_factory_and_dependency_create_async_sessions() -> None:
    database = build_database(DATABASE_URL)

    async def inspect_sessions() -> None:
        async with database.session_factory() as direct_session:
            assert isinstance(direct_session, AsyncSession)

        dependency = get_db_session(database)  # type: ignore[arg-type]
        dependency_session = await anext(dependency)
        try:
            assert isinstance(dependency_session, AsyncSession)
        finally:
            await dependency.aclose()

    try:
        asyncio.run(inspect_sessions())
    finally:
        asyncio.run(database.dispose())


def test_database_disposes_async_engine_once() -> None:
    engine = Mock(spec=AsyncEngine)
    engine.dispose = AsyncMock()
    database = Database(
        engine=cast(AsyncEngine, engine),
        session_factory=cast(async_sessionmaker[AsyncSession], Mock()),
    )

    asyncio.run(database.dispose())

    engine.dispose.assert_awaited_once_with()
