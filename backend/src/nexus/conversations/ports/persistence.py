"""Application-facing Conversation persistence boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from nexus.conversations.domain import Conversation, Generation, Message


class ConversationPersistenceError(Exception):
    """An unexpected Conversation persistence failure occurred."""


class ConversationReferenceError(Exception):
    """A required tenant, Conversation, or Message reference is invalid."""


class ConversationEntityNotFoundError(Exception):
    """A requested Conversation entity cannot be updated."""


class ConversationPersistence(Protocol):
    """Short transaction operations used by Conversation application code.

    Terminal methods return ``True`` only when they commit the authoritative
    transition from ``RUNNING``. A ``False`` result means another terminal
    state already won and must not be overwritten or reported by the caller.
    """

    async def create_conversation(self, conversation: Conversation) -> None: ...

    async def get_conversation(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None: ...

    async def prepare_generation(
        self,
        *,
        organization_public_id: UUID,
        conversation: Conversation,
        message: Message,
        generation: Generation,
        history_limit: int,
    ) -> tuple[Message, ...]: ...

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> bool: ...

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool: ...

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> bool: ...


__all__ = [
    "ConversationEntityNotFoundError",
    "ConversationPersistence",
    "ConversationPersistenceError",
    "ConversationReferenceError",
]
