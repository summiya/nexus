"""Synchronous SQLAlchemy transaction operations for Conversations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar
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

T = TypeVar("T")


class SqlAlchemyConversationPersistence(ConversationPersistence):
    """Run one short repository transaction in a fresh worker session."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def create_conversation(self, conversation: Conversation) -> None:
        await self._run_transaction(
            lambda session: SqlAlchemyConversationRepository(session).add(conversation)
        )

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
        def prepare(session: Session) -> PreparedGeneration:
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
            return PreparedGeneration(
                conversation=conversation,
                history=tuple(history),
            )

        return await self._run_transaction(prepare)

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> None:
        def complete(session: Session) -> None:
            SqlAlchemyMessageRepository(session).add(
                organization_public_id=organization_public_id,
                message=assistant_message,
            )
            SqlAlchemyGenerationRepository(session).update(
                organization_public_id=organization_public_id,
                generation=generation,
            )

        await self._run_transaction(complete)

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await self._update_generation(organization_public_id, generation)

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await self._update_generation(organization_public_id, generation)

    async def _update_generation(
        self,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await self._run_transaction(
            lambda session: SqlAlchemyGenerationRepository(session).update(
                organization_public_id=organization_public_id,
                generation=generation,
            )
        )

    async def _run_transaction(self, operation: Callable[[Session], T]) -> T:
        return await asyncio.to_thread(self._run_transaction_sync, operation)

    def _run_transaction_sync(self, operation: Callable[[Session], T]) -> T:
        with self._session_factory() as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
