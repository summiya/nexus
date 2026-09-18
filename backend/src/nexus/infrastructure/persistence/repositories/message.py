"""SQLAlchemy repository for tenant-scoped Conversation Messages."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nexus.conversations.domain import ConversationMessageRole, Message
from nexus.conversations.ports.repositories import (
    ConversationPersistenceError,
    ConversationReferenceError,
)
from nexus.infrastructure.persistence.models.conversation import (
    Conversation as ConversationModel,
)
from nexus.infrastructure.persistence.models.message import Message as MessageModel
from nexus.infrastructure.persistence.models.organization import Organization


class SqlAlchemyMessageRepository:
    """Persist and query Messages through a tenant-scoped Conversation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        organization_public_id: UUID,
        message: Message,
    ) -> None:
        try:
            reference = self._conversation_reference(
                organization_public_id=organization_public_id,
                conversation_public_id=message.conversation_public_id,
            )
            if reference is None:
                raise ConversationReferenceError("Message Conversation was not found")

            organization_id, conversation_id = reference
            self._session.add(
                MessageModel(
                    public_id=message.public_id,
                    organization_id=organization_id,
                    conversation_id=conversation_id,
                    role=message.role.value,
                    content=message.content,
                    created_at=message.created_at,
                )
            )
            self._session.flush()
        except ConversationReferenceError:
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError("Message persistence failed") from exc

    def list_recent_for_conversation(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
        limit: int,
    ) -> list[Message]:
        if limit <= 0:
            raise ValueError("message history limit must be positive")

        try:
            reference = self._conversation_reference(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation_public_id,
            )
            if reference is None:
                return []

            organization_id, conversation_id = reference
            recent_ids = (
                select(MessageModel.id)
                .where(
                    MessageModel.organization_id == organization_id,
                    MessageModel.conversation_id == conversation_id,
                )
                .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
                .limit(limit)
                .subquery()
            )
            models = self._session.scalars(
                select(MessageModel)
                .where(MessageModel.id.in_(select(recent_ids.c.id)))
                .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
            ).all()
            return [_to_domain(model, conversation_public_id) for model in models]
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError("Message persistence failed") from exc

    def _conversation_reference(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[int, int] | None:
        reference = self._session.execute(
            select(Organization.id, ConversationModel.id)
            .join(
                ConversationModel,
                ConversationModel.organization_id == Organization.id,
            )
            .where(
                Organization.public_id == organization_public_id,
                ConversationModel.public_id == conversation_public_id,
            )
        ).one_or_none()
        if reference is None:
            return None
        return reference[0], reference[1]


def _to_domain(model: MessageModel, conversation_public_id: UUID) -> Message:
    return Message(
        public_id=model.public_id,
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole(model.role),
        content=model.content,
        created_at=model.created_at,
    )
