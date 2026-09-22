"""Retrieve the authorized persisted history for one Conversation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.conversations.domain import ConversationMessageHistoryItem
from nexus.conversations.ports.persistence import (
    ConversationPersistence,
    ConversationPersistenceError,
)
from nexus.errors import ErrorCode, NexusError


@dataclass(frozen=True)
class GetConversationMessages:
    persistence: ConversationPersistence

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        conversation_public_id: UUID,
    ) -> tuple[ConversationMessageHistoryItem, ...]:
        try:
            conversation = await self.persistence.get_conversation(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation_public_id,
            )
            if conversation is None or (
                conversation.workspace_public_id is None
                and conversation.created_by_user_public_id != user_public_id
            ):
                raise NexusError(
                    ErrorCode.NOT_FOUND,
                    "The requested resource was not found.",
                )
            if conversation.workspace_public_id is not None:
                raise NexusError(
                    ErrorCode.FORBIDDEN,
                    "You are not allowed to perform this action.",
                )

            return await self.persistence.list_messages(
                organization_public_id=organization_public_id,
                conversation_public_id=conversation_public_id,
            )
        except ConversationPersistenceError as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The conversation messages could not be retrieved.",
                retryable=True,
            ) from exc
