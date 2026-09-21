"""SQLAlchemy implementation of the Conversation persistence boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nexus.conversations.domain import Conversation, Generation, Message
from nexus.conversations.ports.persistence import (
    ConversationPersistence,
    ConversationPersistenceError,
)
from nexus.infrastructure.persistence import _conversation_queries as queries

T = TypeVar("T")


class SqlAlchemyConversationPersistence(ConversationPersistence):
    """Run each Conversation persistence operation in a fresh worker session."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def create_conversation(self, conversation: Conversation) -> None:
        await self._run_transaction(
            lambda session: queries.insert_conversation(session, conversation)
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

    async def prepare_generation(
        self,
        *,
        organization_public_id: UUID,
        conversation: Conversation,
        message: Message,
        generation: Generation,
        history_limit: int,
    ) -> tuple[Message, ...]:
        def prepare(session: Session) -> tuple[Message, ...]:
            queries.insert_message(
                session,
                organization_public_id=organization_public_id,
                message=message,
            )
            queries.insert_generation(
                session,
                organization_public_id=organization_public_id,
                generation=generation,
            )
            history = queries.list_recent_messages(
                session,
                organization_public_id=organization_public_id,
                conversation_public_id=conversation.public_id,
                limit=history_limit,
            )
            return tuple(history)

        return await self._run_transaction(prepare)

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> None:
        def complete(session: Session) -> None:
            queries.insert_message(
                session,
                organization_public_id=organization_public_id,
                message=assistant_message,
            )
            queries.update_generation(
                session,
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

    def _get_conversation(
        self,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        try:
            with self._session_factory() as session:
                return queries.get_conversation(
                    session,
                    organization_public_id=organization_public_id,
                    conversation_public_id=conversation_public_id,
                )
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc

    async def _update_generation(
        self,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        await self._run_transaction(
            lambda session: queries.update_generation(
                session,
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
            except SQLAlchemyError as exc:
                session.rollback()
                raise ConversationPersistenceError(
                    "Conversation persistence failed"
                ) from exc
            except Exception:
                session.rollback()
                raise
