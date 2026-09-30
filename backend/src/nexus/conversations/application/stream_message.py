"""Streaming Conversation message use case."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from nexus.conversations.application.stream_lifecycle import (
    ConversationStreamLifecycle,
)
from nexus.conversations.domain import (
    ConversationMessageRole,
    Generation,
    GenerationStatus,
    Message,
    conversation_title_from_message,
)
from nexus.conversations.ports.persistence import (
    ConversationGenerationInProgressError,
    ConversationPersistence,
    ConversationRequestAlreadySubmittedError,
)
from nexus.errors import ErrorCode, NexusError
from nexus.llm.domain import LLMError, LLMMessage, LLMRequest, LLMRole
from nexus.model_providers.application import ResolveChatModel
from nexus.model_providers.domain import ConfiguredModelId
from nexus.model_providers.ports import RuntimeChatGateway

_RUNTIME_MODEL_COMPATIBILITY_VALUE = "configured-chat-model"


@dataclass(frozen=True)
class StreamConversationMessageRequest:
    organization_public_id: UUID
    user_public_id: UUID
    conversation_public_id: UUID
    content: str
    model_id: ConfiguredModelId | None = None
    idempotency_key: UUID | None = None


@dataclass(frozen=True)
class StreamConversationMessage:
    persistence: ConversationPersistence
    resolve_chat_model: ResolveChatModel
    runtime_chat_gateway: RuntimeChatGateway
    history_limit: int
    history_max_chars: int
    message_max_length: int

    async def prepare(
        self,
        request: StreamConversationMessageRequest,
    ) -> ConversationStreamLifecycle:
        content = request.content.strip()
        if not content or len(content) > self.message_max_length:
            raise NexusError(ErrorCode.VALIDATION_ERROR, "Invalid message content.")
        conversation = await self.persistence.get_conversation(
            organization_public_id=request.organization_public_id,
            conversation_public_id=request.conversation_public_id,
        )
        if conversation is None or (
            conversation.workspace_public_id is None
            and conversation.created_by_user_public_id != request.user_public_id
        ):
            raise NexusError(
                ErrorCode.NOT_FOUND, "The requested resource was not found."
            )
        if conversation.workspace_public_id is not None:
            raise NexusError(
                ErrorCode.FORBIDDEN,
                "You are not allowed to perform this action.",
            )

        resolved_model = await self.resolve_chat_model.execute(
            organization_public_id=request.organization_public_id,
            model_id=request.model_id,
        )

        now = datetime.now(UTC)
        message = Message(
            public_id=uuid4(),
            conversation_public_id=conversation.public_id,
            role=ConversationMessageRole.USER,
            content=content,
            created_at=now,
        )
        generation = Generation(
            public_id=uuid4(),
            conversation_public_id=conversation.public_id,
            user_message_public_id=message.public_id,
            configured_model_public_id=resolved_model.model_id.value,
            status=GenerationStatus.RUNNING,
            idempotency_key=request.idempotency_key,
            started_at=now,
        )
        lifecycle = ConversationStreamLifecycle(
            persistence=self.persistence,
            organization_public_id=request.organization_public_id,
            conversation=conversation,
            generation=generation,
        )

        initial_title = (
            conversation_title_from_message(content)
            if conversation.title is None
            else None
        )

        try:
            history = await self.persistence.prepare_generation(
                organization_public_id=request.organization_public_id,
                conversation=conversation,
                message=message,
                generation=generation,
                history_limit=self.history_limit,
                initial_title=initial_title,
            )
        except ConversationGenerationInProgressError as exc:
            raise NexusError(
                ErrorCode.CONFLICT,
                "A generation is already in progress for this conversation.",
            ) from exc
        except ConversationRequestAlreadySubmittedError as exc:
            raise NexusError(
                ErrorCode.CONFLICT,
                "This message request has already been accepted.",
            ) from exc
        except asyncio.CancelledError:
            await lifecycle.cancel()
            raise

        try:
            bounded_history = _bounded_history(
                history,
                max_chars=self.history_max_chars,
            )
            llm_request = LLMRequest(
                model=_RUNTIME_MODEL_COMPATIBILITY_VALUE,
                messages=tuple(_to_llm_message(item) for item in bounded_history),
                tools=(),
            )
        except Exception:
            await lifecycle.fail("stream_initialization_failure")
            raise

        try:
            upstream = self.runtime_chat_gateway.stream(
                request=llm_request,
                target=resolved_model,
            )
        except asyncio.CancelledError:
            await lifecycle.cancel()
            raise
        except LLMError as exc:
            await lifecycle.fail(exc.kind.value)
            raise NexusError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The language model service is unavailable.",
                retryable=True,
            ) from exc
        except Exception:
            await lifecycle.fail("stream_initialization_failure")
            raise

        return await lifecycle.start(upstream)


def _bounded_history(
    history: tuple[Message, ...],
    *,
    max_chars: int,
) -> tuple[Message, ...]:
    """Keep the newest chronological history that fits the configured budget."""

    selected: list[Message] = []
    used_chars = 0
    for message in reversed(history):
        next_size = len(message.content)
        if selected and used_chars + next_size > max_chars:
            break
        if not selected and next_size > max_chars:
            selected.append(message)
            break
        selected.append(message)
        used_chars += next_size
    selected.reverse()
    return tuple(selected)


def _to_llm_message(message: Message) -> LLMMessage:
    role = {
        ConversationMessageRole.SYSTEM: LLMRole.SYSTEM,
        ConversationMessageRole.USER: LLMRole.USER,
        ConversationMessageRole.ASSISTANT: LLMRole.ASSISTANT,
    }[message.role]
    return LLMMessage(role=role, content=message.content)
