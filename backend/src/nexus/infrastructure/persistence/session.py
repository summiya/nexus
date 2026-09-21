"""SQLAlchemy database resources owned by one NEXUS application."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def _normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True)
class Database:
    """Application-scoped SQLAlchemy engine and session factory."""

    engine: Engine
    session_factory: Callable[[], Session]

    def dispose(self) -> None:
        self.engine.dispose()


def build_database(database_url: str) -> Database:
    """Build database resources from the owning application's configuration."""

    engine = create_engine(_normalize_database_url(database_url), pool_pre_ping=True)
    return Database(
        engine=engine,
        session_factory=sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        ),
    )
