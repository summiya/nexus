"""Conversation application dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from nexus.conversations.application import (
    CreateConversation,
    StreamConversationMessage,
)


def get_create_conversation(request: Request) -> CreateConversation:
    return request.app.state.conversations.create


def get_stream_conversation_message(request: Request) -> StreamConversationMessage:
    return request.app.state.conversations.stream_message


CreateConversationDep = Annotated[
    CreateConversation,
    Depends(get_create_conversation),
]
StreamConversationMessageDep = Annotated[
    StreamConversationMessage,
    Depends(get_stream_conversation_message),
]
