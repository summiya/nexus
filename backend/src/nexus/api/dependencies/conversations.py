"""Conversation application dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from nexus.api.dependencies import AppContainerDep
from nexus.conversations.application import (
    CreateConversation,
    StreamConversationMessage,
)


def get_create_conversation(container: AppContainerDep) -> CreateConversation:
    return container.conversations.create


def get_stream_conversation_message(
    container: AppContainerDep,
) -> StreamConversationMessage:
    return container.conversations.stream_message


CreateConversationDep = Annotated[
    CreateConversation,
    Depends(get_create_conversation),
]
StreamConversationMessageDep = Annotated[
    StreamConversationMessage,
    Depends(get_stream_conversation_message),
]
