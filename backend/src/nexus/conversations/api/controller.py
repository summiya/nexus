"""Conversation HTTP controller."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.sse import EventSourceResponse, ServerSentEvent, format_sse_event

from nexus.authentication.api.security import CurrentAuthContextDep
from nexus.conversations.api.dependencies import (
    CreateConversationDep,
    StreamConversationMessageDep,
)
from nexus.conversations.api.schemas import (
    ConversationResponseBody,
    CreateConversationRequestBody,
    CreateMessageRequestBody,
)
from nexus.conversations.application.events import (
    ConversationEvent,
    GenerationCompleted,
    GenerationError,
    GenerationStarted,
    GenerationUsage,
    MessageDelta,
)
from nexus.conversations.application.stream_message import (
    StreamConversationMessageRequest,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponseBody, status_code=201)
async def create_conversation(
    body: CreateConversationRequestBody,
    auth_context: CurrentAuthContextDep,
    service: CreateConversationDep,
) -> ConversationResponseBody:
    conversation = await service.execute(
        organization_public_id=auth_context.organization_public_id,
        user_public_id=auth_context.user_public_id,
        title=body.title,
    )
    return ConversationResponseBody(
        public_id=conversation.public_id,
        organization_public_id=conversation.organization_public_id,
        created_by_user_public_id=conversation.created_by_user_public_id,
        workspace_public_id=conversation.workspace_public_id,
        project_public_id=conversation.project_public_id,
        title=conversation.title,
    )


@router.post("/{conversation_public_id}/messages")
async def stream_conversation_message(
    conversation_public_id: UUID,
    body: CreateMessageRequestBody,
    auth_context: CurrentAuthContextDep,
    service: StreamConversationMessageDep,
) -> EventSourceResponse:
    prepared = await service.prepare(
        StreamConversationMessageRequest(
            organization_public_id=auth_context.organization_public_id,
            user_public_id=auth_context.user_public_id,
            conversation_public_id=conversation_public_id,
            content=body.content,
            model=body.model,
        )
    )

    async def events() -> AsyncIterator[bytes]:
        try:
            async for event in prepared:
                server_event = _to_server_sent_event(event)
                yield format_sse_event(
                    data_str=json.dumps(jsonable_encoder(server_event.data)),
                    event=server_event.event,
                    id=server_event.id,
                    retry=server_event.retry,
                    comment=server_event.comment,
                )
        finally:
            await prepared.aclose()

    return EventSourceResponse(events())


def _to_server_sent_event(event: ConversationEvent) -> ServerSentEvent:
    if isinstance(event, GenerationStarted):
        data: dict[str, object] = {
            "conversation_id": str(event.conversation_public_id),
            "generation_id": str(event.generation_public_id),
            "model": event.model,
        }
    elif isinstance(event, MessageDelta):
        data = {
            "conversation_id": str(event.conversation_public_id),
            "generation_id": str(event.generation_public_id),
            "delta": event.delta,
        }
    elif isinstance(event, GenerationUsage):
        data = {
            "generation_id": str(event.generation_public_id),
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "total_tokens": event.total_tokens,
        }
    elif isinstance(event, GenerationCompleted):
        data = {
            "conversation_id": str(event.conversation_public_id),
            "generation_id": str(event.generation_public_id),
            "assistant_message_id": str(event.assistant_message_public_id),
            "finish_reason": event.finish_reason.value,
        }
    else:
        assert isinstance(event, GenerationError)
        data = {
            "generation_id": str(event.generation_public_id),
            "kind": event.kind,
            "message": event.message,
        }
    return ServerSentEvent(event=event.type.value, data=data)
