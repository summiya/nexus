"""SQLAlchemy database resources owned by one NEXUS application."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True)
class Database:
    """Application-scoped asynchronous SQLAlchemy resources."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Dispose the engine and its connection pool."""

        await self.engine.dispose()


def build_database(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> Database:
    """Build database resources from the owning application's configuration."""

    normalized_database_url = _normalize_database_url(database_url)
    engine = create_async_engine(
        normalized_database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )
    return Database(
        engine=engine,
        session_factory=async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        ),
    )
