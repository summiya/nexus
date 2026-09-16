"""SQLAlchemy organization repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.infrastructure.persistence.models.organization import Organization


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def exists_by_slug(self, slug: str) -> bool:
        return (
            self._session.scalar(
                select(Organization.id).where(Organization.slug == slug)
            )
            is not None
        )

    def add(self, organization: Organization) -> None:
        self._session.add(organization)
        self._session.flush()
