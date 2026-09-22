"""SQLAlchemy implementation of the Conversation persistence boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from nexus.conversations.domain import Conversation, Generation, Message
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
        return await self._run_worker(
            lambda: self._get_conversation(
                organization_public_id,
                conversation_public_id,
            )
        )

    async def list_conversations(
        self,
        *,
        organization_public_id: UUID,
        created_by_user_public_id: UUID,
    ) -> tuple[Conversation, ...]:
        return await self._run_worker(
            lambda: self._list_conversations(
                organization_public_id,
                created_by_user_public_id,
            )
        )

    async def list_messages(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[Message, ...]:
        return await self._run_worker(
            lambda: self._list_messages(
                organization_public_id,
                conversation_public_id,
            )
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
    ) -> bool:
        def complete(session: Session) -> bool:
            model = queries.lock_generation_for_terminal_transition(
                session,
                organization_public_id=organization_public_id,
                generation=generation,
            )
            if model is None:
                return False
            queries.insert_message(
                session,
                organization_public_id=organization_public_id,
                message=assistant_message,
            )
            queries.apply_generation_terminal_transition(
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

    def _list_conversations(
        self,
        organization_public_id: UUID,
        created_by_user_public_id: UUID,
    ) -> tuple[Conversation, ...]:
        try:
            with self._session_factory() as session:
                return tuple(
                    queries.list_conversations(
                        session,
                        organization_public_id=organization_public_id,
                        created_by_user_public_id=created_by_user_public_id,
                    )
                )
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc

    def _list_messages(
        self,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[Message, ...]:
        try:
            with self._session_factory() as session:
                return tuple(
                    queries.list_messages(
                        session,
                        organization_public_id=organization_public_id,
                        conversation_public_id=conversation_public_id,
                    )
                )
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError(
                "Conversation persistence failed"
            ) from exc

    async def _transition_generation(
        self,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool:
        def transition(session: Session) -> bool:
            model = queries.lock_generation_for_terminal_transition(
                session,
                organization_public_id=organization_public_id,
                generation=generation,
            )
            if model is None:
                return False
            queries.apply_generation_terminal_transition(
                session,
                model=model,
                generation=generation,
            )
            return True

        return await self._run_transaction(transition)

    async def _run_transaction(self, operation: Callable[[Session], T]) -> T:
        return await self._run_worker(
            lambda: self._run_transaction_sync(operation),
        )

    async def _run_worker(self, operation: Callable[[], T]) -> T:
        """Do not abandon a session-owning worker when its caller is cancelled."""
        worker = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            await _settle_cancelled_worker(worker)
            raise

    def _run_transaction_sync(self, operation: Callable[[Session], T]) -> T:
        with self._session_factory() as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except IntegrityError as exc:
                session.rollback()
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
                session.rollback()
                raise ConversationPersistenceError(
                    "Conversation persistence failed"
                ) from exc
            except Exception:
                session.rollback()
                raise


def _constraint_name(exc: IntegrityError) -> str | None:
    """Return PostgreSQL's violated constraint/index name when available."""
    diagnostic = getattr(exc.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None


async def _settle_cancelled_worker(worker: asyncio.Task[object]) -> None:
    """Wait until a shielded worker has definitely committed or rolled back."""
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            continue
        except BaseException:  # noqa: BLE001 - cancellation remains authoritative
            return

    if worker.cancelled():
        return
    worker.exception()
