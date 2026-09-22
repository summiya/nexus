"""Provider-independent Conversation domain contracts."""

from nexus.conversations.domain.conversation import Conversation
from nexus.conversations.domain.generation import (
    Generation,
    GenerationFinishReason,
    GenerationStatus,
)
from nexus.conversations.domain.history import (
    ConversationGenerationMetadata,
    ConversationMessageHistoryItem,
)
from nexus.conversations.domain.message import ConversationMessageRole, Message

__all__ = [
    "Conversation",
    "ConversationGenerationMetadata",
    "ConversationMessageHistoryItem",
    "ConversationMessageRole",
    "Generation",
    "GenerationFinishReason",
    "GenerationStatus",
    "Message",
]
