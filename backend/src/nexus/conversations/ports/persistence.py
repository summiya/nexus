"""Application-facing Conversation persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from nexus.conversations.domain import Conversation, Generation, Message


@dataclass(frozen=True)
class PreparedGeneration:
    """Committed input state and history prepared for provider execution."""

    conversation: Conversation
    history: tuple[Message, ...]


class ConversationPersistence(Protocol):
    """Short transaction operations used by Conversation application code."""

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
    ) -> PreparedGeneration: ...

    async def complete_generation(
        self,
        *,
        organization_public_id: UUID,
        assistant_message: Message,
        generation: Generation,
    ) -> None: ...

    async def fail_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None: ...

    async def cancel_generation(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None: ...


__all__ = ["ConversationPersistence", "PreparedGeneration"]
