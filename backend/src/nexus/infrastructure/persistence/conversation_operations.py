"""Synchronous SQLAlchemy transaction operations for Conversations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from nexus.conversations.domain import Conversation, Generation, Message
from nexus.conversations.ports.persistence import (
    ConversationPersistence,
    PreparedGeneration,
)
from nexus.infrastructure.persistence.repositories.conversation import (
    SqlAlchemyConversationRepository,
)
from nexus.infrastructure.persistence.repositories.generation import (
    SqlAlchemyGenerationRepository,
)
from nexus.infrastructure.persistence.repositories.message import (
    SqlAlchemyMessageRepository,
)


class SqlAlchemyConversationPersistence(ConversationPersistence):
    """Run one short repository transaction in a fresh worker session."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def create_conversation(self, conversation: Conversation) -> None:
        await asyncio.to_thread(self._create_conversation, conversation)

    def _create_conversation(self, conversation: Conversation) -> None:
        with self._session_factory() as session:
            try:
                SqlAlchemyConversationRepository(session).add(conversation)
                session.commit()
            except Exception:
                session.rollback()
                raise

    async def get_conversation(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        return await asyncio.to_thread(
            self._get_conversation,
            organization_public_id,
            conversation_public_id,
        )

    def _get_conversation(
        self,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        with self._session_factory() as session:
            return SqlAlchemyConversationRepository(session).get(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation_public_id,
            )

    async def prepare_generation(
        self,
        *,
        organization_public_id: UUID,
        conversation: Conversation,
        message: Message,
        generation: Generation,
        history_limit: int,
    ) -> PreparedGeneration:
        return await asyncio.to_thread(
            self._prepare_generation,
            organization_public_id,
            conversation,
            message,
            generation,
            history_limit,
        )

    def _prepare_generation(
        self,
        organization_public_id: UUID,
        conversation: Conversation,
        message: Message,
        generation: Generation,
        history_limit: int,
    ) -> PreparedGeneration:
        with self._session_factory() as session:
            try:
                message_repository = SqlAlchemyMessageRepository(session)
                message_repository.add(
                    organization_public_id=organization_public_id,
                    message=message,
                )
                SqlAlchemyGenerationRepository(session).add(
                    organization_public_id=organization_public_id,
                    generation=generation,
                )
                history = message_repository.list_recent_for_conversation(
                    organization_public_id=organization_public_id,
                    conversation_public_id=conversation.public_id,
                    limit=history_limit,
                )
                session.commit()
                return PreparedGeneration(
                    conversation=conversation,
                    history=tuple(history),
                )
            except Exception:
                session.rollback()
                raise

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> None:
        await asyncio.to_thread(
            self._complete_generation,
            organization_public_id,
            assistant_message,
            generation,
        )

    def _complete_generation(
        self,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> None:
        with self._session_factory() as session:
            try:
                SqlAlchemyMessageRepository(session).add(
                    organization_public_id=organization_public_id,
                    message=assistant_message,
                )
                SqlAlchemyGenerationRepository(session).update(
                    organization_public_id=organization_public_id,
                    generation=generation,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await asyncio.to_thread(
            self._update_generation,
            organization_public_id,
            generation,
        )

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await asyncio.to_thread(
            self._update_generation,
            organization_public_id,
            generation,
        )

    def _update_generation(
        self,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        with self._session_factory() as session:
            try:
                SqlAlchemyGenerationRepository(session).update(
                    organization_public_id=organization_public_id,
                    generation=generation,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
