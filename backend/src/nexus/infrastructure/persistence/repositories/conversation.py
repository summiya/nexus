"""SQLAlchemy repository for tenant-scoped Conversations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nexus.conversations.domain import Conversation
from nexus.conversations.ports.repositories import (
    ConversationPersistenceError,
    ConversationReferenceError,
)
from nexus.infrastructure.persistence.models.conversation import (
    Conversation as ConversationModel,
)
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User


class SqlAlchemyConversationRepository:
    """Persist Conversations while keeping ORM and internal IDs private."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, conversation: Conversation) -> None:
        try:
            reference = self._session.execute(
                select(Organization.id, User.id)
                .join(User, User.organization_id == Organization.id)
                .where(
                    Organization.public_id == conversation.organization_public_id,
                    User.public_id == conversation.created_by_user_public_id,
                )
            ).one_or_none()
            if reference is None:
                raise ConversationReferenceError(
                    "Conversation organization or creator was not found"
                )

            organization_id, creator_id = reference
            self._session.add(
                ConversationModel(
                    public_id=conversation.public_id,
                    organization_id=organization_id,
                    created_by_user_id=creator_id,
                    workspace_public_id=conversation.workspace_public_id,
                    project_public_id=conversation.project_public_id,
                    title=conversation.title,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                )
            )
            self._session.flush()
        except ConversationReferenceError:
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc

    def get(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        try:
            row = self._session.execute(
                select(
                    ConversationModel,
                    Organization.public_id,
                    User.public_id,
                )
                .join(
                    Organization,
                    ConversationModel.organization_id == Organization.id,
                )
                .join(
                    User,
                    (User.id == ConversationModel.created_by_user_id)
                    & (User.organization_id == ConversationModel.organization_id),
                )
                .where(
                    Organization.public_id == organization_public_id,
                    ConversationModel.public_id == conversation_public_id,
                )
            ).one_or_none()
            if row is None:
                return None

            model, organization_id, creator_id = row
            return Conversation(
                public_id=model.public_id,
                organization_public_id=organization_id,
                created_by_user_public_id=creator_id,
                workspace_public_id=model.workspace_public_id,
                project_public_id=model.project_public_id,
                title=model.title,
                created_at=model.created_at,
                updated_at=model.updated_at,
            )
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc
