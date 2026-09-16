"""SQLAlchemy session boundary for application use cases."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from nexus.config.settings import settings


def _normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


engine = create_engine(
    _normalize_database_url(settings.database_url), pool_pre_ping=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Iterator[Session]:
    """Yield one database session for a request."""
    with SessionLocal() as session:
        yield session
