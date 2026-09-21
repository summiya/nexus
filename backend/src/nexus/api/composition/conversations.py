"""Conversation API composition root."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.config.settings import Settings
from nexus.conversations.application import (
    CreateConversation,
    StreamConversationMessage,
)
from nexus.infrastructure.persistence.conversation_operations import (
    SqlAlchemyConversationPersistence,
)
from nexus.infrastructure.persistence.session import SessionLocal
from nexus.llm.application import ModelPolicy, Stream


@dataclass(frozen=True)
class ConversationComposition:
    create: CreateConversation
    stream_message: StreamConversationMessage


def build_conversation_composition(
    app_settings: Settings,
    llm_stream: Stream,
    model_policy: ModelPolicy,
) -> ConversationComposition:
    persistence = SqlAlchemyConversationPersistence(SessionLocal)
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
