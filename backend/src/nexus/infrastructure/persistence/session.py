"""SQLAlchemy database resources owned by one NEXUS application."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker


def _normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True)
class Database:
    """Application-scoped sync and async SQLAlchemy resources.

    The synchronous resources remain available while existing persistence adapters
    are migrated to native async SQLAlchemy in later phases.
    """

    engine: Engine
    session_factory: sessionmaker[Session]
    async_engine: AsyncEngine
    async_session_factory: async_sessionmaker[AsyncSession]

    def dispose(self) -> None:
        """Dispose the transitional synchronous engine."""

        self.engine.dispose()

    async def dispose_async(self) -> None:
        """Dispose the asynchronous engine and its connection pool."""

        await self.async_engine.dispose()


def build_database(database_url: str) -> Database:
    """Build database resources from the owning application's configuration."""

    normalized_database_url = _normalize_database_url(database_url)
    engine = create_engine(normalized_database_url, pool_pre_ping=True)
    async_engine = create_async_engine(
        normalized_database_url,
        pool_pre_ping=True,
    )
    return Database(
        engine=engine,
        session_factory=sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        ),
        async_engine=async_engine,
        async_session_factory=async_sessionmaker(
            bind=async_engine,
            autoflush=False,
            expire_on_commit=False,
        ),
    )
