"""List Conversations owned by an authenticated user."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.conversations.domain import Conversation
from nexus.conversations.ports.persistence import (
    ConversationPersistence,
    ConversationPersistenceError,
)
from nexus.errors import ErrorCode, NexusError


@dataclass(frozen=True)
class ListConversations:
    persistence: ConversationPersistence

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
    ) -> tuple[Conversation, ...]:
        try:
            return await self.persistence.list_conversations(
                organization_public_id=organization_public_id,
                created_by_user_public_id=user_public_id,
            )
        except ConversationPersistenceError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The conversations could not be retrieved.",
                retryable=True,
            ) from exc
