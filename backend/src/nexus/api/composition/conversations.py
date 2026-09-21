"""Conversation API composition root."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from nexus.config.settings import Settings
from nexus.conversations.application import (
    CreateConversation,
    StreamConversationMessage,
)
from nexus.infrastructure.persistence.conversation_operations import (
    SqlAlchemyConversationPersistence,
)
from nexus.llm.application import ModelPolicy, Stream


@dataclass(frozen=True)
class ConversationComposition:
    create: CreateConversation
    stream_message: StreamConversationMessage


def build_conversation_composition(
    app_settings: Settings,
    llm_stream: Stream,
    model_policy: ModelPolicy,
    session_factory: Callable[[], Session],
) -> ConversationComposition:
    persistence = SqlAlchemyConversationPersistence(session_factory)
    return ConversationComposition(
        create=CreateConversation(persistence=persistence),
        stream_message=StreamConversationMessage(
            persistence=persistence,
            llm_stream=llm_stream,
            model_policy=model_policy,
            history_limit=app_settings.conversation_history_limit,
            history_max_chars=app_settings.conversation_history_max_chars,
            message_max_length=app_settings.conversation_message_max_length,
        ),
    )
