"""Standalone Conversation creation use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from nexus.conversations.domain import Conversation
from nexus.conversations.ports.persistence import ConversationPersistence
from nexus.errors import ErrorCode, NexusError


@dataclass(frozen=True)
class CreateConversation:
    persistence: ConversationPersistence

    async def execute(
        self,
        *,
        organization_public_id: UUID,
        user_public_id: UUID,
        title: str | None,
    ) -> Conversation:
        normalized_title = title.strip() if title is not None else None
        now = datetime.now(UTC)
        conversation = Conversation(
            public_id=uuid4(),
            organization_public_id=organization_public_id,
            created_by_user_public_id=user_public_id,
            workspace_public_id=None,
            project_public_id=None,
            title=normalized_title or None,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.persistence.create_conversation(conversation)
        except Exception as exc:
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The conversation could not be created.",
                retryable=True,
            ) from exc
        return conversation
