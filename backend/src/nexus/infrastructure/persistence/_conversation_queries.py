"""Private SQLAlchemy queries for Conversation persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.conversations.domain import (
    Conversation,
    ConversationGenerationMetadata,
    ConversationMessageHistoryItem,
    ConversationMessageRole,
    Generation,
    GenerationFinishReason,
    GenerationStatus,
    Message,
)
from nexus.conversations.ports.persistence import (
    ConversationEntityNotFoundError,
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
from nexus.infrastructure.persistence.models.user import User


def insert_conversation(session: Session, conversation: Conversation) -> None:
    reference = session.execute(
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
    session.add(
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
    session.flush()


def get_conversation(
    session: Session,
    *,
    organization_public_id: UUID,
    conversation_public_id: UUID,
) -> Conversation | None:
    row = session.execute(
        select(ConversationModel, Organization.public_id, User.public_id)
        .join(Organization, ConversationModel.organization_id == Organization.id)
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

    model, stored_organization_public_id, creator_public_id = row
    return _to_conversation(
        model,
        organization_public_id=stored_organization_public_id,
        created_by_user_public_id=creator_public_id,
    )


def list_conversations(
    session: Session,
    *,
    organization_public_id: UUID,
    created_by_user_public_id: UUID,
) -> list[Conversation]:
    rows = session.execute(
        select(ConversationModel, Organization.public_id, User.public_id)
        .join(Organization, ConversationModel.organization_id == Organization.id)
        .join(
            User,
            (User.id == ConversationModel.created_by_user_id)
            & (User.organization_id == ConversationModel.organization_id),
        )
        .where(
            Organization.public_id == organization_public_id,
            User.public_id == created_by_user_public_id,
        )
        .order_by(ConversationModel.created_at.desc(), ConversationModel.id.desc())
    ).all()
    return [
        _to_conversation(
            model,
            organization_public_id=stored_organization_public_id,
            created_by_user_public_id=creator_public_id,
        )
        for model, stored_organization_public_id, creator_public_id in rows
    ]


def _to_conversation(
    model: ConversationModel,
    *,
    organization_public_id: UUID,
    created_by_user_public_id: UUID,
) -> Conversation:
    return Conversation(
        public_id=model.public_id,
        organization_public_id=organization_public_id,
        created_by_user_public_id=created_by_user_public_id,
        workspace_public_id=model.workspace_public_id,
        project_public_id=model.project_public_id,
        title=model.title,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def insert_message(
    session: Session,
    *,
    organization_public_id: UUID,
    message: Message,
) -> None:
    reference = _conversation_reference(
        session,
        organization_public_id=organization_public_id,
        conversation_public_id=message.conversation_public_id,
    )
    if reference is None:
        raise ConversationReferenceError("Message Conversation was not found")

    organization_id, conversation_id = reference
    session.add(
        MessageModel(
            public_id=message.public_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            role=message.role.value,
            content=message.content,
            created_at=message.created_at,
        )
    )
    session.flush()


def list_messages(
    session: Session,
    *,
    organization_public_id: UUID,
    conversation_public_id: UUID,
) -> list[ConversationMessageHistoryItem]:
    reference = _conversation_reference(
        session,
        organization_public_id=organization_public_id,
        conversation_public_id=conversation_public_id,
    )
    if reference is None:
        return []

    organization_id, conversation_id = reference
    rows = session.execute(
        select(MessageModel, GenerationModel)
        .outerjoin(
            GenerationModel,
            (GenerationModel.organization_id == MessageModel.organization_id)
            & (GenerationModel.conversation_id == MessageModel.conversation_id)
            & (GenerationModel.assistant_message_id == MessageModel.id),
        )
        .where(
            MessageModel.organization_id == organization_id,
            MessageModel.conversation_id == conversation_id,
        )
        .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
    ).all()
    return [
        ConversationMessageHistoryItem(
            message=_to_message(message_model, conversation_public_id),
            generation=(
                _to_generation_metadata(generation_model)
                if message_model.role == ConversationMessageRole.ASSISTANT.value
                and generation_model is not None
                else None
            ),
        )
        for message_model, generation_model in rows
    ]


def list_recent_messages(
    session: Session,
    *,
    organization_public_id: UUID,
    conversation_public_id: UUID,
    limit: int,
) -> list[Message]:
    if limit <= 0:
        raise ValueError("message history limit must be positive")

    reference = _conversation_reference(
        session,
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
    models = session.scalars(
        select(MessageModel)
        .where(MessageModel.id.in_(select(recent_ids.c.id)))
        .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
    ).all()
    return [_to_message(model, conversation_public_id) for model in models]


def insert_generation(
    session: Session,
    *,
    organization_public_id: UUID,
    generation: Generation,
) -> None:
    reference = _conversation_reference(
        session,
        organization_public_id=organization_public_id,
        conversation_public_id=generation.conversation_public_id,
    )
    if reference is None:
        raise ConversationReferenceError("Generation Conversation was not found")

    organization_id, conversation_id = reference
    user_message_id, assistant_message_id = _message_references(
        session,
        organization_id=organization_id,
        conversation_id=conversation_id,
        generation=generation,
    )
    session.add(
        GenerationModel(
            public_id=generation.public_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            model=generation.model,
            status=generation.status.value,
            idempotency_key=generation.idempotency_key,
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
    session.flush()


def lock_generation_for_terminal_transition(
    session: Session,
    *,
    organization_public_id: UUID,
    generation: Generation,
) -> GenerationModel | None:
    if generation.status not in {
        GenerationStatus.COMPLETED,
        GenerationStatus.FAILED,
        GenerationStatus.CANCELLED,
    }:
        raise ValueError("generation transition must target a terminal status")

    row = session.execute(
        select(GenerationModel, MessageModel.public_id)
        .join(Organization, GenerationModel.organization_id == Organization.id)
        .join(
            ConversationModel,
            (ConversationModel.id == GenerationModel.conversation_id)
            & (ConversationModel.organization_id == GenerationModel.organization_id),
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
        .with_for_update(of=GenerationModel)
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

    if model.status in {
        GenerationStatus.COMPLETED.value,
        GenerationStatus.FAILED.value,
        GenerationStatus.CANCELLED.value,
    }:
        return None
    if model.status != GenerationStatus.RUNNING.value:
        raise ValueError("stored Generation is not ready for a terminal transition")
    return model


def apply_generation_terminal_transition(
    session: Session,
    *,
    model: GenerationModel,
    generation: Generation,
) -> None:
    model.assistant_message_id = _assistant_message_reference(
        session,
        organization_id=model.organization_id,
        conversation_id=model.conversation_id,
        assistant_message_public_id=generation.assistant_message_public_id,
    )
    model.status = generation.status.value
    model.finish_reason = (
        generation.finish_reason.value if generation.finish_reason is not None else None
    )
    model.input_tokens = generation.input_tokens
    model.output_tokens = generation.output_tokens
    model.total_tokens = generation.total_tokens
    model.started_at = generation.started_at
    model.completed_at = generation.completed_at
    model.error_kind = generation.error_kind
    session.flush()


def _conversation_reference(
    session: Session,
    *,
    organization_public_id: UUID,
    conversation_public_id: UUID,
) -> tuple[int, int] | None:
    reference = session.execute(
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


def _message_references(
    session: Session,
    *,
    organization_id: int,
    conversation_id: int,
    generation: Generation,
) -> tuple[int, int | None]:
    public_ids = [generation.user_message_public_id]
    if generation.assistant_message_public_id is not None:
        public_ids.append(generation.assistant_message_public_id)
    rows = session.execute(
        select(MessageModel.public_id, MessageModel.id).where(
            MessageModel.organization_id == organization_id,
            MessageModel.conversation_id == conversation_id,
            MessageModel.public_id.in_(public_ids),
        )
    ).all()
    message_ids = {public_id: message_id for public_id, message_id in rows}
    if any(public_id not in message_ids for public_id in public_ids):
        raise ConversationReferenceError("Generation Message reference was not found")
    assistant_message_id = (
        message_ids[generation.assistant_message_public_id]
        if generation.assistant_message_public_id is not None
        else None
    )
    return message_ids[generation.user_message_public_id], assistant_message_id


def _assistant_message_reference(
    session: Session,
    *,
    organization_id: int,
    conversation_id: int,
    assistant_message_public_id: UUID | None,
) -> int | None:
    if assistant_message_public_id is None:
        return None
    message_id = session.scalar(
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


def _to_message(model: MessageModel, conversation_public_id: UUID) -> Message:
    return Message(
        public_id=model.public_id,
        conversation_public_id=conversation_public_id,
        role=ConversationMessageRole(model.role),
        content=model.content,
        created_at=model.created_at,
    )


def _to_generation_metadata(
    model: GenerationModel,
) -> ConversationGenerationMetadata:
    return ConversationGenerationMetadata(
        public_id=model.public_id,
        model=model.model,
        status=GenerationStatus(model.status),
        finish_reason=(
            GenerationFinishReason(model.finish_reason)
            if model.finish_reason is not None
            else None
        ),
        input_tokens=model.input_tokens,
        output_tokens=model.output_tokens,
        total_tokens=model.total_tokens,
        started_at=model.started_at,
        completed_at=model.completed_at,
        error_kind=model.error_kind,
    )
