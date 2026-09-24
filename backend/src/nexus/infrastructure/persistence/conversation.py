"""SQLAlchemy implementation of the Conversation persistence boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.conversations.domain import (
    Conversation,
    ConversationMessageHistoryItem,
    Generation,
    Message,
)
from nexus.conversations.ports.persistence import (
    ConversationGenerationInProgressError,
    ConversationPersistence,
    ConversationPersistenceError,
    ConversationRequestAlreadySubmittedError,
)
from nexus.infrastructure.persistence import _conversation_queries as queries

T = TypeVar("T")

_ACTIVE_GENERATION_INDEX = "uq_generations_one_running_per_conversation"
_IDEMPOTENCY_INDEX = "uq_generations_conversation_idempotency_key"


class SqlAlchemyConversationPersistence(ConversationPersistence):
    """Run each Conversation persistence operation in a fresh async session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
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
        return await self._run_read(
            lambda session: queries.get_conversation(
                session,
                organization_public_id=organization_public_id,
                conversation_public_id=conversation_public_id,
            )
        )

    async def list_conversations(
        self,
        *,
        organization_public_id: UUID,
        created_by_user_public_id: UUID,
    ) -> tuple[Conversation, ...]:
        conversations = await self._run_read(
            lambda session: queries.list_conversations(
                session,
                organization_public_id=organization_public_id,
                created_by_user_public_id=created_by_user_public_id,
            )
        )
        return tuple(conversations)

    async def list_messages(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[ConversationMessageHistoryItem, ...]:
        messages = await self._run_read(
            lambda session: queries.list_messages(
                session,
                organization_public_id=organization_public_id,
                conversation_public_id=conversation_public_id,
            )
        )
        return tuple(messages)

    async def prepare_generation(
        self,
        *,
        organization_public_id: UUID,
        conversation: Conversation,
        message: Message,
        generation: Generation,
        history_limit: int,
    ) -> tuple[Message, ...]:
        async def prepare(session: AsyncSession) -> tuple[Message, ...]:
            await queries.insert_message(
                session,
                organization_public_id=organization_public_id,
                message=message,
            )
            await queries.insert_generation(
                session,
                organization_public_id=organization_public_id,
                generation=generation,
            )
            history = await queries.list_recent_messages(
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
    ) -> bool:
        async def complete(session: AsyncSession) -> bool:
            model = await queries.lock_generation_for_terminal_transition(
                session,
                organization_public_id=organization_public_id,
                generation=generation,
            )
            if model is None:
                return False
            await queries.insert_message(
                session,
                organization_public_id=organization_public_id,
                message=assistant_message,
            )
            await queries.apply_generation_terminal_transition(
                session,
                model=model,
                generation=generation,
            )
            return True

        return await self._run_transaction(complete)

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool:
        return await self._transition_generation(organization_public_id, generation)

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool:
        return await self._transition_generation(organization_public_id, generation)

    async def _transition_generation(
        self,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool:
        async def transition(session: AsyncSession) -> bool:
            model = await queries.lock_generation_for_terminal_transition(
                session,
                organization_public_id=organization_public_id,
                generation=generation,
            )
            if model is None:
                return False
            await queries.apply_generation_terminal_transition(
                session,
                model=model,
                generation=generation,
            )
            return True

        return await self._run_transaction(transition)

    async def _run_read(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        try:
            async with self._session_factory() as session:
                return await operation(session)
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc

    async def _run_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        transaction = asyncio.create_task(self._execute_transaction(operation))
        try:
            return await asyncio.shield(transaction)
        except asyncio.CancelledError:
            await _settle_cancelled_transaction(transaction)
            raise

    async def _execute_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
    ) -> T:
        try:
            async with self._session_factory.begin() as session:
                return await operation(session)
        except IntegrityError as exc:
            constraint_name = _constraint_name(exc)
            if constraint_name == _ACTIVE_GENERATION_INDEX:
                raise ConversationGenerationInProgressError(
                    "Conversation already has a running Generation"
                ) from exc
            if constraint_name == _IDEMPOTENCY_INDEX:
                raise ConversationRequestAlreadySubmittedError(
                    "Conversation message request was already submitted"
                ) from exc
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc


def _constraint_name(exc: IntegrityError) -> str | None:
    """Return PostgreSQL's violated constraint/index name when available."""
    diagnostic = getattr(exc.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None


async def _settle_cancelled_transaction(transaction: asyncio.Task[object]) -> None:
    """Wait until a shielded transaction has definitely committed or rolled back."""
    while not transaction.done():
        try:
            await asyncio.shield(transaction)
        except asyncio.CancelledError:
            continue
        except BaseException:  # noqa: BLE001 - cancellation remains authoritative
            return

    if transaction.cancelled():
        return
    transaction.exception()
