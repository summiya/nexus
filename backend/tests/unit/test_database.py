import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from nexus.api.dependencies.database import get_async_db_session
from nexus.infrastructure.persistence.session import Database, build_database

DATABASE_URL = "postgresql://test:secret@localhost:5432/nexus_test"


def test_build_database_creates_sync_and_async_postgresql_resources() -> None:
    database = build_database(DATABASE_URL)

    try:
        assert isinstance(database.engine, Engine)
        assert isinstance(database.async_engine, AsyncEngine)
        assert database.engine.url.drivername == "postgresql+psycopg"
        assert database.async_engine.url.drivername == "postgresql+psycopg"
        assert database.engine.url.database == "nexus_test"
        assert database.async_engine.url.database == "nexus_test"
    finally:
        database.dispose()
        asyncio.run(database.dispose_async())


def test_explicit_psycopg_url_remains_supported() -> None:
    database = build_database(
        "postgresql+psycopg://test:secret@localhost:5432/nexus_test"
    )

    try:
        assert database.engine.url.drivername == "postgresql+psycopg"
        assert database.async_engine.url.drivername == "postgresql+psycopg"
    finally:
        database.dispose()
        asyncio.run(database.dispose_async())


def test_sync_session_factory_remains_available_during_transition() -> None:
    database = build_database(DATABASE_URL)

    try:
        with database.session_factory() as session:
            assert isinstance(session, Session)
    finally:
        database.dispose()
        asyncio.run(database.dispose_async())


def test_async_session_factory_and_dependency_create_async_sessions() -> None:
    database = build_database(DATABASE_URL)

    async def inspect_sessions() -> None:
        async with database.async_session_factory() as direct_session:
            assert isinstance(direct_session, AsyncSession)

        dependency = get_async_db_session(database)  # type: ignore[arg-type]
        dependency_session = await anext(dependency)
        try:
            assert isinstance(dependency_session, AsyncSession)
        finally:
            await dependency.aclose()

    try:
        asyncio.run(inspect_sessions())
    finally:
        database.dispose()
        asyncio.run(database.dispose_async())


def test_database_disposes_sync_and_async_engines() -> None:
    sync_engine = Mock(spec=Engine)
    async_engine = Mock(spec=AsyncEngine)
    async_engine.dispose = AsyncMock()
    database = Database(
        engine=cast(Engine, sync_engine),
        session_factory=cast(sessionmaker[Session], Mock()),
        async_engine=cast(AsyncEngine, async_engine),
        async_session_factory=cast(async_sessionmaker[AsyncSession], Mock()),
    )

    database.dispose()
    asyncio.run(database.dispose_async())

    sync_engine.dispose.assert_called_once_with()
    async_engine.dispose.assert_awaited_once_with()
