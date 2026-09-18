"""SQLAlchemy repository for tenant-scoped Conversation Generations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nexus.conversations.domain import Generation
from nexus.conversations.ports.repositories import (
    ConversationEntityNotFoundError,
    ConversationPersistenceError,
    ConversationReferenceError,
)
from nexus.infrastructure.persistence.models.conversation import (
    Conversation as ConversationModel,
)
from nexus.infrastructure.persistence.models.generation import (
    Generation as GenerationModel,
)
from nexus.infrastructure.persistence.models.message import Message as MessageModel
from nexus.infrastructure.persistence.models.organization import Organization


class SqlAlchemyGenerationRepository:
    """Persist Generation attempts without owning lifecycle decisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        try:
            organization_id, conversation_id = self._conversation_reference(
                organization_public_id=organization_public_id,
                conversation_public_id=generation.conversation_public_id,
            )
            message_ids = self._message_references(
                organization_id=organization_id,
                conversation_id=conversation_id,
                generation=generation,
            )
            self._session.add(
                GenerationModel(
                    public_id=generation.public_id,
                    organization_id=organization_id,
                    conversation_id=conversation_id,
                    user_message_id=message_ids[0],
                    assistant_message_id=message_ids[1],
                    model=generation.model,
                    status=generation.status.value,
                    finish_reason=(
                        generation.finish_reason.value
                        if generation.finish_reason is not None
                        else None
                    ),
                    input_tokens=generation.input_tokens,
                    output_tokens=generation.output_tokens,
                    total_tokens=generation.total_tokens,
                    started_at=generation.started_at,
                    completed_at=generation.completed_at,
                    error_kind=generation.error_kind,
                )
            )
            self._session.flush()
        except ConversationReferenceError:
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError("Generation persistence failed") from exc

    def update(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        try:
            row = self._session.execute(
                select(GenerationModel, MessageModel.public_id)
                .join(
                    Organization,
                    GenerationModel.organization_id == Organization.id,
                )
                .join(
                    ConversationModel,
                    (ConversationModel.id == GenerationModel.conversation_id)
                    & (
                        ConversationModel.organization_id
                        == GenerationModel.organization_id
                    ),
                )
                .join(
                    MessageModel,
                    (MessageModel.id == GenerationModel.user_message_id)
                    & (MessageModel.conversation_id == GenerationModel.conversation_id)
                    & (MessageModel.organization_id == GenerationModel.organization_id),
                )
                .where(
                    Organization.public_id == organization_public_id,
                    ConversationModel.public_id == generation.conversation_public_id,
                    GenerationModel.public_id == generation.public_id,
                )
            ).one_or_none()
            if row is None:
                raise ConversationEntityNotFoundError("Generation was not found")

            model, user_message_public_id = row
            if (
                user_message_public_id != generation.user_message_public_id
                or model.model != generation.model
            ):
                raise ConversationReferenceError(
                    "Generation identity does not match the stored Generation"
                )

            assistant_message_id = self._assistant_message_reference(
                organization_id=model.organization_id,
                conversation_id=model.conversation_id,
                assistant_message_public_id=generation.assistant_message_public_id,
            )
            model.assistant_message_id = assistant_message_id
            model.status = generation.status.value
            model.finish_reason = (
                generation.finish_reason.value
                if generation.finish_reason is not None
                else None
            )
            model.input_tokens = generation.input_tokens
            model.output_tokens = generation.output_tokens
            model.total_tokens = generation.total_tokens
            model.started_at = generation.started_at
            model.completed_at = generation.completed_at
            model.error_kind = generation.error_kind
            self._session.flush()
        except (ConversationEntityNotFoundError, ConversationReferenceError):
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError("Generation persistence failed") from exc

    def _conversation_reference(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[int, int]:
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
            raise ConversationReferenceError("Generation Conversation was not found")
        return reference[0], reference[1]

    def _message_references(
        self,
        *,
        organization_id: int,
        conversation_id: int,
        generation: Generation,
    ) -> tuple[int, int | None]:
        public_ids = [generation.user_message_public_id]
        if generation.assistant_message_public_id is not None:
            public_ids.append(generation.assistant_message_public_id)
        rows = self._session.execute(
            select(MessageModel.public_id, MessageModel.id).where(
                MessageModel.organization_id == organization_id,
                MessageModel.conversation_id == conversation_id,
                MessageModel.public_id.in_(public_ids),
            )
        ).all()
        message_ids = {public_id: message_id for public_id, message_id in rows}
        if any(public_id not in message_ids for public_id in public_ids):
            raise ConversationReferenceError(
                "Generation Message reference was not found"
            )
        assistant_id = (
            message_ids[generation.assistant_message_public_id]
            if generation.assistant_message_public_id is not None
            else None
        )
        return message_ids[generation.user_message_public_id], assistant_id

    def _assistant_message_reference(
        self,
        *,
        organization_id: int,
        conversation_id: int,
        assistant_message_public_id: UUID | None,
    ) -> int | None:
        if assistant_message_public_id is None:
            return None
        message_id = self._session.scalar(
            select(MessageModel.id).where(
                MessageModel.organization_id == organization_id,
                MessageModel.conversation_id == conversation_id,
                MessageModel.public_id == assistant_message_public_id,
            )
        )
        if message_id is None:
            raise ConversationReferenceError(
                "Generation assistant Message reference was not found"
            )
        return message_id
