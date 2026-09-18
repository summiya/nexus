"""Repository contracts for the Conversation capability."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from nexus.conversations.domain import Conversation, Generation, Message


class ConversationRepositoryError(Exception):
    """Base error for Conversation repository boundaries."""


class ConversationReferenceError(ConversationRepositoryError):
    """A required tenant, Conversation, or Message reference is invalid."""


class ConversationEntityNotFoundError(ConversationRepositoryError):
    """A requested Conversation entity cannot be updated."""


class ConversationPersistenceError(ConversationRepositoryError):
    """An unexpected persistence failure occurred."""


class ConversationRepository(Protocol):
    """Tenant-scoped Conversation persistence capabilities."""

    def add(self, conversation: Conversation) -> None:
        """Persist and flush a Conversation without committing."""

    def get(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
    ) -> Conversation | None:
        """Return a Conversation only inside the requested organization."""


class MessageRepository(Protocol):
    """Tenant- and Conversation-scoped Message persistence capabilities."""

    def add(
        self,
        *,
        organization_public_id: UUID,
        message: Message,
    ) -> None:
        """Persist and flush a Message without committing."""

    def list_recent_for_conversation(
        self,
        *,
        organization_public_id: UUID,
        conversation_public_id: UUID,
        limit: int,
    ) -> list[Message]:
        """Return the newest bounded slice in chronological order."""


class GenerationRepository(Protocol):
    """Tenant- and Conversation-scoped Generation persistence capabilities."""

    def add(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        """Persist and flush a Generation without committing."""

    def update(
        self,
        *,
        organization_public_id: UUID,
        generation: Generation,
    ) -> None:
        """Persist lifecycle fields without changing Generation identity."""
