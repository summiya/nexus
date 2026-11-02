"""Provider-independent LLM domain contracts."""

from nexus.llm.domain.embeddings import (
    MAX_EMBEDDING_BATCH_SIZE,
    MAX_EMBEDDING_INPUT_BYTES,
    EmbeddingRequest,
    EmbeddingResult,
)
from nexus.llm.domain.errors import (
    LLMAuthenticationError,
    LLMContentRejectedError,
    LLMError,
    LLMErrorKind,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnknownProviderError,
)
from nexus.llm.domain.events import (
    LLMCompletedEvent,
    LLMErrorEvent,
    LLMEvent,
    LLMEventType,
    LLMStartedEvent,
    LLMTextDeltaEvent,
    LLMToolCallCompletedEvent,
    LLMToolCallDeltaEvent,
    LLMToolCallStartedEvent,
    LLMUsageEvent,
)
from nexus.llm.domain.messages import LLMMessage, LLMRole
from nexus.llm.domain.requests import LLMRequest
from nexus.llm.domain.responses import LLMFinishReason, LLMResponse
from nexus.llm.domain.tools import LLMToolCall, LLMToolDefinition
from nexus.llm.domain.usage import LLMUsage

__all__ = [
    "MAX_EMBEDDING_BATCH_SIZE",
    "MAX_EMBEDDING_INPUT_BYTES",
    "EmbeddingRequest",
    "EmbeddingResult",
    "LLMAuthenticationError",
    "LLMCompletedEvent",
    "LLMContentRejectedError",
    "LLMError",
    "LLMErrorEvent",
    "LLMErrorKind",
    "LLMEvent",
    "LLMEventType",
    "LLMFinishReason",
    "LLMInvalidRequestError",
    "LLMMessage",
    "LLMProviderUnavailableError",
    "LLMRateLimitedError",
    "LLMRequest",
    "LLMResponse",
    "LLMRole",
    "LLMStartedEvent",
    "LLMTextDeltaEvent",
    "LLMTimeoutError",
    "LLMToolCall",
    "LLMToolCallCompletedEvent",
    "LLMToolCallDeltaEvent",
    "LLMToolCallStartedEvent",
    "LLMToolDefinition",
    "LLMUnknownProviderError",
    "LLMUsage",
    "LLMUsageEvent",
]
