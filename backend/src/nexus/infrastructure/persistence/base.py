"""SQLAlchemy declarative base for NEXUS persistence models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for persisted NEXUS ORM models."""
